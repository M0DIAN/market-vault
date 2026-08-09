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

import ast
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

EXPECTED_VERSION = "0.6.1"
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
# The CI fresh-wheel public API smoke marker must use the v0.6.1 marker.
CI_PUBLIC_API_MARKER = "V061_PUBLIC_API_IMPORT_OK"
# The CI fresh-wheel smoke must also exercise the PR-2 ArtifactClient
# foundation, the PR-3 verified readers, and the PR-4 Catalog client
# surface, each printing its own v0.7.0 marker.
CI_V070_PUBLIC_API_MARKER = "V070_PUBLIC_API_IMPORT_OK"
CI_V070_PUBLIC_API_IMPORT_LINES = (
    "from market_vault import ArtifactClient",
    "ArtifactClient()",
    "assert callable(client.load_canonical_build)",
    "assert callable(client.load_dataset)",
    "assert callable(client.load_dataset_catalog)",
)
CI_V070_CATALOG_CLIENT_MARKER = "V070_CATALOG_CLIENT_IMPORT_OK"
CI_V070_CATALOG_CLIENT_IMPORT_LINES = (
    "cat = client.load_dataset_catalog",
    "assert callable(cb) and callable(ds) and callable(cat)",
    "print('V070_CATALOG_CLIENT_IMPORT_OK')",
)
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
# Facts the v0.6.1 direction document must state now that v0.6.1 is
# formally released: the released status, the frozen baseline, the fixed
# 4-PR sequence with the full merge record (PR-1..PR-4, including the
# PR #47 release commit), the released lifecycle truth (tag created, GitHub
# Release published, PyPI/TestPyPI NOT PUBLISHED), and the pointer to the
# v0.7.0 direction.
V061_DIRECTION_FACTS = (
    "Status: released on 2026-08-08",
    "Stability, Auditability, and Usability Maintenance",
    "669c955abc0a234264964dfdb7fcafdf502a901a",
    "v0.6.0",
    "package version at planning time: 0.6.0",
    "PR-1",
    "PR-2",
    "PR-3",
    "PR-4",
    "Post-release baseline + maintenance direction",
    "CLI/help/error/usability consistency polish",
    "CI/package auditability + maintenance hardening",
    "v0.6.1 release preparation",
    "0.6.0 through PR-3",
    "bumped to 0.6.1 only in PR-4",
    "maintenance release",
    "PR-1 COMPLETE: PR #44 merged at",
    "6bb9a9500fae53511ff964f47e5ccea20f3d91f7",
    "PR-2 COMPLETE: PR #45 merged at",
    "33d7f5856bf060527ccf4d2ab679df4429009ce6",
    "PR-3 COMPLETE: PR #46 merged at",
    "99c2e7bd445333740806dedec4aed03f82f32b11",
    "PR-4 COMPLETE: PR #47 merged at",
    "37614d539171ef7b738e47415f3cd6ca2de332d1",
    "31257004716",
    "V0.6.1 is formally released",
    "The v0.6.1 tag is created",
    "The GitHub Release MarketVault v0.6.1 is published",
    "2026-08-08T13:06:51Z",
    "PyPI: NOT PUBLISHED",
    "TestPyPI: NOT PUBLISHED",
    "docs/v0_7_0_direction.md",
)
# The v0.6.1 direction document must not regress to stale current-state
# wording: the release-preparation narrative (PR-4 as the current stage,
# "not formally released", tag/GitHub Release not created) and the
# pre-release status are all stale now that v0.6.1 is released.
V061_DIRECTION_STALE_PHRASES = (
    "Status: planned",
    "Status: implementation complete; v0.6.1 release preparation",
    "The release is not started",
    "PR-1 is the current maintenance-baseline and direction stage",
    "PR-2 has not started",
    "PR-2 is the current CLI/help/error/usability consistency-polish stage",
    "PR-3 has not started",
    "Status: planned maintenance release",
    "V0.6.1 maintenance development is in PR-3",
    "PR-3 is the current CI/package auditability and maintenance-hardening stage",
    "PR-4 has not started",
    "PR-4 is the current v0.6.1 release-preparation stage",
    "The package version is now 0.6.1 in PR-4",
    "V0.6.1 is NOT formally released",
    "The v0.6.1 tag has not been created",
    "The GitHub Release v0.6.1 has not been published",
    "Package remains 0.6.0",
)
# Affirmative publication claims that must never appear in the v0.6.1
# direction document: PyPI and TestPyPI are NOT PUBLISHED.
V061_DIRECTION_RELEASE_CLAIMS = (
    "PyPI: PUBLISHED",
    "TestPyPI: PUBLISHED",
)
# The v0.6.1 direction document must mark the explicit non-goals; none of
# them may be smuggled into a v0.6.1 PR.
V061_DIRECTION_NONGOAL_MARKERS = (
    "Python Client",
    "REST API",
    "Dataset Catalog query command",
    "new Catalog capability",
    "new Sample Generation capability",
    "identity v2",
    "schema v2",
    "new artifact format",
    "dependency modernization",
    "PyArrow runtime pin",
    "ML training",
    "backtesting",
    "signals",
    "automatic trading",
    "Trading Execution",
)
# The frozen v0.6.1 invariants the direction document must state.
V061_DIRECTION_INVARIANT_MARKERS = (
    "Canonical identity algorithms unchanged",
    "Dataset identity algorithms unchanged",
    "Sample Generation identity unchanged",
    "Catalog content identity unchanged",
    "Catalog snapshot identity unchanged",
    "Dataset build-plan contract unchanged",
    "Sample Generation contract unchanged",
    "Catalog formal contract unchanged",
    "existing immutable artifacts require no migration/rewrite",
    "CLI command set unchanged",
)
# Facts the v0.6.1 CLI usability audit document (the PR-2 deliverable)
# must state.
V061_CLI_USABILITY_AUDIT_MARKERS = (
    "MarketVault v0.6.1 CLI Usability Audit",
    "6bb9a9500fae53511ff964f47e5ccea20f3d91f7",
)
# Facts the v0.6.1 CI and package audit document (the PR-3 deliverable)
# must state.
V061_CI_PACKAGE_AUDIT_MARKERS = (
    "MarketVault v0.6.1 CI and Package Auditability",
    "33d7f5856bf060527ccf4d2ab679df4429009ce6",
    "actions/checkout@v6",
    "actions/setup-python@v6",
    "actions/upload-artifact@v7",
    "SHA256SUMS.txt",
    "artifact-digest",
    "github.event.pull_request.head.sha",
    "V061_PACKAGE_AUDIT_OK",
)
# Contradictory claims that must never appear in the v0.6.1 direction
# document even when the required non-goal markers are present.
V061_DIRECTION_FALSE_CLAIMS = (
    "Python Client is part of v0.6.1",
    "adds the Python Client",
    "adds the Dataset Catalog query command",
    "0.6.1 in PR-1",
    "0.6.1 in PR-2",
    "0.6.1 in PR-3",
)
# Facts the v0.6.1 release notes must state now that v0.6.1 is formally
# released: the formal release status, the full merge record
# (PR-1..PR-4 including the PR #47 release commit), the released lifecycle
# truth (tag created, GitHub Release published, PyPI/TestPyPI NOT
# PUBLISHED), the formal asset hashes, and the candidate-vs-formal artifact
# distinction. The historical release-preparation record keeps the
# preparation-time facts verbatim.
V061_RELEASE_NOTES_FACTS = (
    "## Formal release status",
    "formally released",
    "PR-4: PR #47 MERGED",
    "2026-08-08T12:20:16Z",
    "37614d539171ef7b738e47415f3cd6ca2de332d1",
    "31257004716",
    "The annotated `v0.6.1` tag was created",
    "0e0508065a6330d643e7801823e908fee881afc9",
    "GitHub Release: MarketVault v0.6.1",
    "MarketVault v0.6.1",
    "367204479",
    "2026-08-08T13:06:51Z",
    "PyPI: NOT PUBLISHED",
    "TestPyPI: NOT PUBLISHED",
    "99c2e7bd445333740806dedec4aed03f82f32b11",
    "PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7",
    "PR-2: PR #45 MERGED 33d7f5856bf060527ccf4d2ab679df4429009ce6",
    "PR-3: PR #46 MERGED 99c2e7bd445333740806dedec4aed03f82f32b11",
    "PR-4: current release-preparation stage, OPEN / UNMERGED",
    "package version in PR-4: 0.6.1",
    "v0.6.1 tag:            NOT CREATED",
    "GitHub Release v0.6.1: NOT PUBLISHED",
    "PyPI:                  NOT PUBLISHED",
    "TestPyPI:              NOT PUBLISHED",
    "No future merge SHA was claimed",
    "no formal artifact SHA256 values",
    "candidate validation only",
    "CI audit artifact",
    "exact main release commit was verified",
    "PR candidate hashes: not reused as formal release asset hashes",
    "new product capabilities = 0",
    "8fd8ec510a7724742d6e3e9fbca5c73b07e991cb3fa35002af792a8dd64ed550",
    "0cadd537a0980978a9a0878766cb2234f5b419f3f5d3874ef92e300c76c756f1",
)
# Stale pre-release wording that must never appear in the current-state
# region of the v0.6.1 release notes (the formal text before the historical
# release-preparation record). The historical sections may quote the
# preparation-time state verbatim, but these precise current-state
# sentences are forbidden in the formal region. "v0.6.1 is released" and
# "v0.6.1 has been released" are now legal formal-state expressions and are
# not stale.
V061_RELEASE_NOTES_STALE_PHRASES = (
    "## Release preparation status",
    "NOT formally released",
    "PR-4 is open",
    "PR-4: current release-preparation stage, OPEN / UNMERGED",
    "package version in PR-4",
    "v0.6.1 tag:            NOT CREATED",
    "GitHub Release v0.6.1: NOT PUBLISHED",
    "PyPI:                  NOT PUBLISHED",
    "TestPyPI:              NOT PUBLISHED",
    "PyPI: PUBLISHED",
    "TestPyPI: PUBLISHED",
    "No future merge SHA is claimed",
    "no formal artifact SHA256 values are predicted",
    "exact future v0.6.1 release commit",
)
# Facts the v0.6.0 direction document must state now that v0.6.0 is
# formally released. The planning sections may keep the historical
# planning-time facts.
V060_DIRECTION_FACTS = (
    "Status: released on 2026-08-08",
    "Deterministic Sample Generation and Dataset Catalog",
    "a978eef291d5e26d20e5cf977bc76609c227cb52",
    "package version at planning time: 0.5.1",
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
    "release preparation",
    "PR #43",
    "MERGED",
    "669c955abc0a234264964dfdb7fcafdf502a901a",
    "31227915770",
    "v0.6.0",
    "MarketVault v0.6.0",
    "2026-08-08T03:17:48Z",
    "PyPI",
    "TestPyPI",
    "NOT PUBLISHED",
    "24a2243031b5f16fdbb9334f1a1722e56eb7a2f7",
    "PR #42",
    "2026-08-07T18:32:32Z",
    "PR-8 COMPLETE",
    "main verified",
    "31207428151",
)
# The v0.6.0 direction document must mark the explicit non-goals.
V060_DIRECTION_NONGOAL_MARKERS = (
    "explicit non-goals",
    "model training",
    "backtesting",
    "automatic trading",
)
# Stale lifecycle wording that must never appear in the current-state
# regions of the v0.6.0 direction document (the header and the Progress
# section). The planning sections may quote the pre-PR-9 state, but the
# current-state regions must describe the formal released state exactly.
V060_DIRECTION_STALE_PHRASES = (
    "Status: implementation complete; v0.6.0 release preparation",
    "Status: planned",
    "Status: proposed",
    "PR-9 is the current v0.6.0 release-preparation stage",
    "PR-9 is open and not merged",
    "PR-8 (this PR)",
    "PR-9 has not started",
    "every supported PyArrow writer",
    "not formally released",
)
# False release claims that must never appear anywhere in the v0.6.0
# direction document: the GitHub Release exists, but no PyPI / TestPyPI
# publication was made.
V060_DIRECTION_RELEASE_CLAIMS = (
    "PyPI published",
    "TestPyPI published",
)
# Facts the v0.6.0 release notes must state now that v0.6.0 is formally
# released. The historical release-preparation record keeps the
# preparation-time facts (PR-9, PR-8 base, candidate validation only).
RELEASE_V060_FACTS = (
    "Formal release status",
    "PR #43",
    "MERGED",
    "2026-08-07T23:41:36Z",
    "669c955abc0a234264964dfdb7fcafdf502a901a",
    "31227915770",
    "v0.6.0",
    "MarketVault v0.6.0",
    "2026-08-08T03:17:48Z",
    "market_vault-0.6.0-py3-none-any.whl",
    "B1BC7D945A8DDF981AEB4AB2B973E5A8BD07919D7293DED15A7715BC03B262AF",
    "market_vault-0.6.0.tar.gz",
    "DBA631EC71BD6FD56A436DEB1F82481FAA3E3E89BA5D03D207870F2C96AF3C37",
    "PyPI: NOT PUBLISHED",
    "TestPyPI: NOT PUBLISHED",
    "PR-9",
    "0.6.0",
    "24a2243031b5f16fdbb9334f1a1722e56eb7a2f7",
    "PR #42",
    "2026-08-07T18:32:32Z",
    "31207428151",
    "Deterministic Sample Generator",
    "Dataset Catalog",
    "sample-generate",
    "dataset-catalog-build",
    "dataset-catalog-verify",
    "dataset-catalog-list",
    "dataset-catalog-show",
    "PyArrow 24.0.0",
    "PyArrow 25.0.0",
    "pyarrow>=16",
    "candidate validation only",
    "exact release commit",
    "no standalone",
    "dataset-catalog-query",
)
# Stale release-preparation current-state sentences that must never appear
# in the formal region of the v0.6.0 release notes (before the historical
# release-preparation record). The historical sections may quote the
# preparation-time state, but these precise current-state sentences are
# forbidden in the formal region.
RELEASE_V060_STALE_PHRASES = (
    "PR-9 is open and **not merged**.",
    "The v0.6.0 tag does **not** exist yet.",
    "No GitHub Release exists yet.",
    "describes the **v0.6.0 release preparation** stage.",
    "not formally released",
    "PyPI: published",
    "PR-8 (this PR)",
    "PR-9 has not started",
    "every supported PyArrow writer",
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
# Stale lifecycle wording that must never appear in the Sample Generation
# contract document: the Dataset Catalog was separately implemented in
# PR-5/6/7 and is no longer a not-implemented dependency.
SAMPLE_GENERATION_CONTRACT_STALE_PHRASES = (
    "Dataset Catalog (PR-5+) is not implemented",
)
# Stale lifecycle wording that must never appear in the Dataset Catalog
# contract document: PR-8 has started and completed, and the CLI is
# implemented by PR-7.
DATASET_CATALOG_CONTRACT_STALE_PHRASES = (
    "PR-8 has not started",
    "Catalog CLI is not implemented",
    "CLI remains PR-7 and is not implemented",
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
    "PR #37",
    "2026-08-06T23:23:50Z",
    "ca486a19e6795940f21a9a22053fc59175510d91",
    "PR-4 is complete",
)
# Contradictory claims that must never appear in the v0.6.0 direction
# document's PR-4 record (the completed-stage wording must stay factual).
V060_DIRECTION_PR4_FALSE_CLAIMS = (
    "V0.6.0 is released",
)
# Facts the v0.6.0 direction document must state about the PR-6 stage.
V060_DIRECTION_PR6_FACTS = (
    "PR-5 merged",
    "PR #39",
    "2958697dd434c536c39267b6a654dabb762c74f9",
    "PR-6 merged",
    "PR #40",
    "997bb337f73f1205d9180c4c532a6679666a312f",
    "PR-6 is complete",
    "not released",
)
# Contradictory claims that must never appear in the v0.6.0 direction
# document's PR-6 record.
V060_DIRECTION_PR6_FALSE_CLAIMS = (
    "V0.6.0 is released",
)
# Facts the v0.6.0 direction document must state about the merged PR-7
# stage.
V060_DIRECTION_PR7_FACTS = (
    "PR #41",
    "PR-7 merged",
    "2026-08-07T13:25:52Z",
    "15ce0ef",
    "PR-7 COMPLETE",
    "main verified",
)
# Contradictory claims that must never appear in the v0.6.0 direction
# document's PR-7 record.
V060_DIRECTION_PR7_FALSE_CLAIMS = (
    "V0.6.0 is released",
)
# Facts the v0.6.0 direction document must state about the PR-8 stage.
V060_DIRECTION_PR8_FACTS = (
    "PR #42",
    "2026-08-07T18:32:32Z",
    "24a2243031b5f16fdbb9334f1a1722e56eb7a2f7",
    "PR-8 COMPLETE",
    "main verified",
    "31207428151",
    "0.5.1",
)
# Contradictory claims that must never appear in the v0.6.0 direction
# document's PR-8 record.
V060_DIRECTION_PR8_FALSE_CLAIMS = (
    "V0.6.0 is released",
)
# Required facts the v0.6.0 integrated acceptance document must state.
V060_ACCEPTANCE_FACTS = (
    "Integrated Acceptance",
    "determinism",
    "corruption",
    "recovery",
    "portability",
    "security",
    "usability",
    "PyArrow 24.0.0",
    "PyArrow 25.0.0",
    "pyarrow>=16",
    "static reference artifact",
    "physical source provenance",
    # The upstream source / curated snapshot Parquet bytes are the
    # identity-bearing physical source provenance.
    "upstream source / curated",
    # The Canonical output Parquet artifact layout is distinct from the
    # upstream source provenance input.
    "Canonical output Parquet",
    # Catalog snapshot _SUCCESS must be exactly empty bytes.
    "exactly empty",
    "PR-9",
    "0.5.1",
    "not released",
)
# Contradictory claims that must never appear in the v0.6.0 integrated
# acceptance document even when the required facts are present.
V060_ACCEPTANCE_FALSE_CLAIMS = (
    # Over-strong portability claim: only the two audited PyArrow
    # runtimes/readers (24.0.0 and 25.0.0) are proven.
    "every supported PyArrow writer",
    # False cross-writer claim: the source Parquet physical bytes DIFFER.
    "byte-identical across writers",
    "identical physical bytes across writers",
    # False provenance claim: physical_snapshot_hash IS part of the
    # physical source provenance.
    "physical_snapshot_hash is not part of",
    "physical_snapshot_hash does not enter",
    # PR-9 must never be claimed started or released.
    "PR-9 has started",
    "PR-9 is in progress",
    "PR-9 merged",
)
# An affirmative "v0.6.0 is released" claim is rejected; the legitimate
# "v0.6.0 is not released" wording is allowed.
V060_RELEASED_RE = re.compile(r"(?<!not )v0\.6\.0 is released", re.IGNORECASE)
# The frozen static reference artifact identity values (mutation guards).
FROZEN_FIXTURE_GENERATION_ID = (
    "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb3"
)
FROZEN_RELATIVE_PLAN_SHA256 = (
    "78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964b"
)
FROZEN_FIXTURE_BUILD_ID = (
    "ce939b043010eb3a4c12b063734edd320bb44801bbfa44715010d5330935a124"
)
# The exact static reference artifact bundle byte size (mutation guard).
FROZEN_BUNDLE_BYTE_SIZE = 38661
# The v0.6.0 Dataset Catalog contract production modules that must exist.
DATASET_CATALOG_MODULES = (
    "src/market_vault/dataset/dataset_catalog_models.py",
    "src/market_vault/dataset/dataset_catalog_identity.py",
    "src/market_vault/dataset/dataset_catalog_projection.py",
)
# The exact version constants the contract models module must define.
DATASET_CATALOG_VERSION_CONSTANTS = (
    "market-vault-dataset-catalog-contract-v1",
    "market-vault-dataset-catalog-entry-v1",
    "market-vault-dataset-catalog-content-v1",
)
# The public functions the contract modules must define.
DATASET_CATALOG_FUNCTIONS = (
    "def catalog_dataset_content_id",
    "def dataset_catalog_content_id",
    "def project_dataset_catalog_entry",
)
# The exact content-facts fields the formal contract document must state.
DATASET_CATALOG_FACTS_FIELDS = (
    "dataset_id",
    "dataset_kind",
    "status",
    "logical_row_count",
    "dataset_schema_id",
    "logical_dataset_content_id",
    "dataset_as_of",
    "scope",
    "feature_spec_pins",
    "label_spec_pins",
    "split_spec_pin",
    "canonical_build_pins",
    "canonical_row_version_ids",
    "completion",
)
# Facts the formal Dataset Catalog contract document must state about the
# PR-5 layer.
DATASET_CATALOG_PR5_FACTS = (
    "VerifiedDatasetBuild",
    "project_dataset_catalog_entry",
    "DatasetCatalogDatasetFacts",
    "DatasetCatalogObservedMetadata",
    "DatasetCatalogEntry",
    "dataset_catalog_content_id",
    "catalog_dataset_content_id",
    "structurally disjoint",
    "first-wins, last-wins, and path-wins are never used",
    "PR-6",
    "PR-7",
)
# Excluded facts the formal Dataset Catalog contract document must state
# never enter the content identity.
DATASET_CATALOG_EXCLUDED_FACTS = (
    "machine / hostname",
    "cwd",
    "mtime",
    "current time",
    "scan order",
    "candidate input order",
    "moving the same verified Dataset to another parent directory",
)
# Contradictory claims that must never appear in the formal Dataset
# Catalog contract document even when the required facts are present.
DATASET_CATALOG_PR5_FALSE_CLAIMS = (
    "trusts manifests directly",
    "Dataset Catalog builder is implemented",
    "verified Catalog reader is implemented",
)
# An affirmative "reuses the legacy Catalog's tables" claim is rejected;
# the legitimate "never reuses the legacy Catalog's tables" wording is
# allowed.
DATASET_CATALOG_REUSES_LEGACY_RE = re.compile(
    r"(?<!never )(?<!not )reuses the legacy Catalog's tables"
)
# The PR-6 production modules that must exist.
DATASET_CATALOG_PR6_MODULES = (
    "src/market_vault/dataset/dataset_catalog_builder.py",
    "src/market_vault/dataset/dataset_catalog_builder_models.py",
    "src/market_vault/dataset/dataset_catalog_serialization.py",
    "src/market_vault/dataset/dataset_catalog_snapshot_identity.py",
    "src/market_vault/dataset/dataset_catalog_materialization.py",
    "src/market_vault/dataset/dataset_catalog_materialization_models.py",
    "src/market_vault/dataset/dataset_catalog_reader.py",
    "src/market_vault/dataset/dataset_catalog_reader_models.py",
)
# The exact PR-6 version constants the modules must define.
DATASET_CATALOG_PR6_VERSION_CONSTANTS = (
    "market-vault-dataset-catalog-builder-v1",
    "market-vault-dataset-catalog-snapshot-v1",
    "market-vault-dataset-catalog-snapshot-manifest-v1",
    "market-vault-dataset-catalog-snapshot-id-v1",
    "market-vault-dataset-catalog-materializer-v1",
    "market-vault-verified-dataset-catalog-reader-v1",
)
# The public PR-6 functions the modules must define.
DATASET_CATALOG_PR6_FUNCTIONS = (
    "def build_dataset_catalog",
    "def materialize_dataset_catalog_snapshot",
    "def load_verified_dataset_catalog",
)
# The PR-7 CLI production modules that must exist.
DATASET_CATALOG_CLI_MODULES = (
    "src/market_vault/dataset/dataset_catalog_cli.py",
    "src/market_vault/dataset/dataset_catalog_cli_models.py",
)
# The four formal PR-7 commands that must be registered.
DATASET_CATALOG_CLI_COMMANDS = (
    "dataset-catalog-build",
    "dataset-catalog-verify",
    "dataset-catalog-list",
    "dataset-catalog-show",
)
# The exact CLI version constants the CLI models module must define.
DATASET_CATALOG_CLI_VERSION_CONSTANTS = (
    "market-vault-dataset-catalog-cli-v1",
    "market-vault-dataset-catalog-cli-result-v1",
)
# The CLI must call exactly the formal Builder -> Materializer -> Reader
# chain; it never implements a second builder / validator / reader.
DATASET_CATALOG_CLI_FUNCTIONS = (
    "build_dataset_catalog(",
    "materialize_dataset_catalog_snapshot(",
    "load_verified_dataset_catalog(",
)
# Forbidden patterns in the CLI module (mutation guards). The exact
# "load_verified_dataset(" pattern can never match the formal
# "load_verified_dataset_catalog(" reader call.
DATASET_CATALOG_CLI_FORBIDDEN_PATTERNS = (
    "dataset-catalog-query",
    "--latest",
    "--force",
    "--overwrite",
    "load_settings(",
    "storage.catalog",
    "from market_vault.storage import Catalog",
    "duckdb",
    "load_verified_dataset(",
    '"catalog.json"',
    '"manifest.json"',
)
# Facts the formal Dataset Catalog contract document must state about the
# PR-7 CLI (Part C).
DATASET_CATALOG_CLI_CONTRACT_FACTS = (
    "market-vault dataset-catalog-build",
    "market-vault dataset-catalog-verify",
    "market-vault dataset-catalog-list",
    "market-vault dataset-catalog-show",
    "market-vault-dataset-catalog-cli-v1",
    "market-vault-dataset-catalog-cli-result-v1",
    "settings-independent",
    "AND semantics",
    "no standalone `dataset-catalog-query`",
    "historical",
    "exit 0 / 1 / 2",
)
# Contradictory PR-7 claims that must never appear in the formal Dataset
# Catalog contract document even when the required facts are present.
# The "a latest pointer" phrase of Part A / Part B always appears in a
# negated context ("... are never implicit inputs", "no latest pointer");
# the false claim is therefore the affirmative maintenance wording, which
# never occurs in the PR-5 / PR-6 text.
DATASET_CATALOG_CLI_FALSE_CLAIMS = (
    "repairs the snapshot",
    "maintains a latest pointer",
)
# The CI fresh-wheel smoke must cover the four Catalog CLI help commands.
CI_PR7_API_MARKER = "PR7_CATALOG_CLI_HELP_OK"
# The CI package job must carry the v0.6.1 release-state marker (the
# released-state marker; the stale preparation marker V061_RELEASE_PREP_OK
# must never be restored), the public API smoke must import
# generate_sample_requests, and the wheel contents check must forbid
# *.b64 fixture bundles.
CI_V061_RELEASE_STATE_MARKER = "V061_RELEASE_STATE_OK"
CI_V061_PUBLIC_API_IMPORT_LINES = ("generate_sample_requests",)
CI_PR7_HELP_COMMANDS = (
    "market-vault dataset-catalog-build --help",
    "market-vault dataset-catalog-verify --help",
    "market-vault dataset-catalog-list --help",
    "market-vault dataset-catalog-show --help",
)
# The dataset package must export the PR-6 public API.
DATASET_CATALOG_PR6_EXPORTS = (
    "build_dataset_catalog",
    "materialize_dataset_catalog_snapshot",
    "load_verified_dataset_catalog",
    "DatasetCatalogBuildResult",
    "DatasetCatalogBuildError",
    "DatasetCatalogMaterializationResult",
    "DatasetCatalogMaterializationError",
    "DatasetCatalogArtifactValidationError",
    "VerifiedDatasetCatalogSnapshot",
    "DATASET_CATALOG_BUILDER_VERSION",
    "DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION",
    "DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION",
    "DATASET_CATALOG_SNAPSHOT_ID_VERSION",
    "DATASET_CATALOG_MATERIALIZER_VERSION",
    "DATASET_CATALOG_READER_CONTRACT_VERSION",
)
# Contract-fact markers the PR-6 modules must keep (mutation guards for
# the fixed trust and identity boundaries).
DATASET_CATALOG_PR6_TRUST_MARKERS = (
    # The builder admits a candidate only through the formal verified
    # Dataset reader and the projection.
    "load_verified_dataset(candidate)",
    "project_dataset_catalog_entry(verified)",
    # The root discovery is a bounded direct-children scan.
    "os.scandir(dataset_root)",
    # The reader treats the recorded location as historical text.
    "historical observed location",
    "never reloaded",
    # The materializer commits with a true no-replace atomic publication.
    "_atomic_rename_directory_no_replace(staging, final)",
    # Write-return validation (never silently accepting a bad write).
    "type(written) is not int or written != len(data)",
)
# Forbidden patterns in the PR-6 modules (mutation guards).
DATASET_CATALOG_PR6_FORBIDDEN_PATTERNS = {
    "src/market_vault/dataset/dataset_catalog_builder.py": (
        "rglob",
        "os.walk",
        "json.loads",  # the builder never parses a manifest itself
        '"manifest.json"',
        "Path.cwd()",  # cwd is never a formal-input dependency
    ),
    "src/market_vault/dataset/dataset_catalog_reader.py": (
        "load_verified_dataset(",
        "Path.resolve(",
    ),
    "src/market_vault/dataset/dataset_catalog_materialization.py": (
        "os.replace(",
        "shutil.move(",
        '"latest"',
    ),
    "src/market_vault/dataset/dataset_catalog_identity.py": (
        '"built_at":',
        '"build_path":',
    ),
    "src/market_vault/dataset/dataset_catalog_snapshot_identity.py": (
        '"output_root"',
        '"snapshot_path"',
    ),
}
# The CI fresh-wheel smoke must also cover the PR-6 public API imports.
CI_PR6_API_MARKER = "PR6_CATALOG_API_IMPORT_OK"
CI_PR6_API_IMPORT_LINES = (
    "build_dataset_catalog",
    "materialize_dataset_catalog_snapshot",
    "load_verified_dataset_catalog",
)
# The formal contract document must state the explicit-absolute builder
# input contract (the formal-input boundary never depends on cwd).
DATASET_CATALOG_PR6_PATH_CONTRACT_MARKERS = (
    "lexically absolute safe path",
    "never an implicit input",
)
# The dataset package must export the PR-5 public API.
DATASET_CATALOG_EXPORTS = (
    "DATASET_CATALOG_CONTRACT_VERSION",
    "DatasetCatalogDatasetFacts",
    "DatasetCatalogObservedMetadata",
    "DatasetCatalogEntry",
    "catalog_dataset_content_id",
    "dataset_catalog_content_id",
    "project_dataset_catalog_entry",
)
# Hardening markers the contract models module must keep: the row-version
# coverage direction (Catalog-level list must be a subset of the pinned
# union, exactly like the Dataset identity contract), the SpecPin business
# key (kind, name, version — never content_sha256), the unsafe identity
# text rejection, and the entry location binding (build_path basename must
# equal dataset_id).
DATASET_CATALOG_HARDENING_MARKERS = (
    "set(canonical_row_version_ids) - covered",
    "key = (pin.kind, pin.name, pin.version)",
    "reject_unsafe_text(text, label)",
    "!= self.dataset_facts.dataset_id",
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
# Facts the v0.6.1 maintenance section of the README must state: the
# fixed maintenance scope (three areas, no new capability), the CLI and CI
# auditability content, and the published-and-sealed release truth.
README_V061_SECTION_MARKERS = (
    "## V0.6.1 stability, auditability, and usability maintenance",
    "V0.6.1 adds NO new product capability",
    "### A. Lifecycle / release-state truth",
    "### B. CLI usability wording",
    "### C. CI/package auditability",
    "No command, business argument, default, exit-code, or JSON behavior changes",
    "actions/checkout@v6",
    "actions/setup-python@v6",
    "actions/upload-artifact@v7",
    "SHA256SUMS.txt",
    "V061_PACKAGE_AUDIT_OK",
    "runtime dependencies unchanged",
    "CLI command set unchanged",
    "no artifact migration/rewrite",
    "v0.6.1 formal release is published and sealed",
    "37614d539171ef7b738e47415f3cd6ca2de332d1",
    "MarketVault v0.6.1",
    "PyPI: NOT PUBLISHED",
    "TestPyPI: NOT PUBLISHED",
)
# Stale pre-release claims that must never appear in the README: the
# v0.6.1 formal release is now published and sealed, and the README must
# never claim it was not released or that the release state is pending.
README_V061_STALE_PHRASES = (
    "the v0.6.1 formal release does not exist yet",
)
# Facts the v0.7.0 direction document must state: the active PR-5
# feature-development status, the v0.6.1 baseline, the PR-1 / PR-2 / PR-3
# / PR-4 merged records, the NOT RELEASED v0.7.0 state, the fixed 6-PR
# sequence with the exact stage names, the version rules (0.6.1 through
# PR-5, 0.7.0 only in PR-6), the explicit non-goals, the historical
# PR-2 / PR-3 / PR-4 boundaries, and the PR-5 boundary.
V070_DIRECTION_FACTS = (
    "# MarketVault v0.7.0 Direction: Python Client and Read-only Artifact Access",
    "Status: active feature development; PR-5 Integrated E2E + usability stage",
    "base version: v0.6.1",
    "37614d539171ef7b738e47415f3cd6ca2de332d1",
    "v0.7.0: NOT RELEASED",
    "PR-1: COMPLETE / MERGED / MAIN VERIFIED",
    "PR-2: COMPLETE / MERGED / MAIN VERIFIED",
    "PR-3: COMPLETE / MERGED / MAIN VERIFIED",
    "PR-4: COMPLETE / MERGED / MAIN VERIFIED",
    "PR-5: CURRENT",
    "PR-6: NOT STARTED",
    "package: 0.6.1",
    "PR-1 record",
    "PR #48 merged at 2026-08-08T23:50:24Z",
    "bad62ee51e8eda03c7c5f20ac858973923e5f93d",
    "31284875166",
    "PR-2 record",
    "PR #49 merged at 2026-08-09T01:24:46Z",
    "1a3ca95a6765e4418e753f1fec6d5c79b8e49e2f",
    "42c63ebfb0c2dfc91b1d61860bed2106faf1bba0",
    "31288212317",
    "ArtifactClient foundation: IMPLEMENTED",
    "Canonical / Dataset / Catalog reads at PR-2: NOT IMPLEMENTED",
    "PR-3 record",
    "PR #50 merged at 2026-08-09T05:34:20Z",
    "01d40bd9a090dc1e23d9539aa57a8649c0d64b7c",
    "61a2b055163815d463d5b261f5b6a94e54e515bd",
    "31296976872",
    "ArtifactClient Canonical verified read: IMPLEMENTED",
    "ArtifactClient Dataset verified read: IMPLEMENTED",
    "Dataset Catalog client read at PR-3: NOT IMPLEMENTED",
    "PR-4 record",
    "PR #51 merged at 2026-08-09T07:42:17Z",
    "49dbc9fdc53d40d0955febe61c87e9cb71dcc159",
    "8b6bb12355c64d02c7e4f73fc67b6222ff2af6ed",
    "31301770295",
    "ArtifactClient Dataset Catalog verified read: IMPLEMENTED",
    "PR-1 — Post-v0.6.1 release baseline",
    "PR-2 — Settings-independent ArtifactClient foundation",
    "PR-3 — Canonical + Dataset verified read-only client access",
    "PR-4 — Dataset Catalog verified read-only client access",
    "PR-5 — Integrated E2E",
    "PR-6 — v0.7.0 release preparation",
    "Then a separate explicit GitHub Release gate",
    "PR-1: 0.6.1",
    "PR-2: 0.6.1",
    "PR-3: 0.6.1",
    "PR-4: 0.6.1",
    "PR-5: 0.6.1",
    "PR-6: 0.6.1 -> 0.7.0",
    "the version is bumped to 0.7.0 only in PR-6",
    "No early 0.7.0 version bump",
    "PR-2 (the merged foundation PR, #49) implemented only",
    "the `ArtifactClient` class foundation",
    "a stateless zero-argument constructor",
    "the lazy top-level package export",
    "foundation tests and the fresh-wheel public API smoke",
    "PR-2 did not implement",
    "Canonical reader methods",
    "Dataset reader methods",
    "Dataset Catalog reader methods",
    "filesystem artifact access",
    "discovery / latest",
    "network / OpenD",
    "future method stubs",
    "PR-3 (the merged reader PR, #50) implemented only",
    "`load_canonical_build`",
    "`load_dataset`",
    "direct formal verified reader delegation",
    "reader-access tests",
    "contract/direction/checker changes",
    "fresh-wheel API smoke updates",
    "PR-3 did not implement",
    "Dataset Catalog client access",
    "Catalog lookup/filter",
    "any writer/builder",
    "discovery/latest",
    "settings",
    "OpenD/network",
    "current-time behavior",
    "CLI",
    "PR-4/5/6 work",
    "PR-4 (the merged Catalog-read PR, #51) implemented only",
    "`load_dataset_catalog`",
    "direct formal verified Catalog reader delegation",
    "Catalog reader access tests",
    "contract/direction/checker changes",
    "fresh-wheel smoke updates",
    "PR-4 did not implement",
    "Catalog builder",
    "Catalog materialization",
    "Catalog list/filter/query convenience API",
    "new CLI",
    "dataset-catalog-query CLI",
    "Canonical/Dataset production changes",
    "artifact format change",
    "schema change",
    "identity change",
    "migration",
    "settings",
    "discovery/latest",
    "network/OpenD",
    "current time",
    "PR-5 usability/examples",
    "PR-6 release prep",
    "version bump",
    "## 6.4 PR-5 boundary",
    "PR-5 (this PR) MAY ONLY",
    "add integrated offline E2E acceptance",
    "add explicit-path Python consumer documentation",
    "add Jupyter-friendly consumer documentation",
    "add ML-consumer handoff documentation without ML implementation",
    "add source-tree examples",
    "harden backward compatibility tests",
    "harden release checker",
    "add existing-job CI smoke for PR-5 examples/acceptance",
    "PR-5 MUST NOT",
    "modify src/",
    "modify dependencies",
    "modify version",
    "add ArtifactClient capabilities",
    "add CLI",
    "add discovery/latest",
    "add settings",
    "add network/OpenD",
    "add current time",
    "add visualization product code",
    "add ML/training/evaluation",
    "perform PR-6 release preparation",
    "No new CLI command",
    "No REST API",
    "No HTTP",
    "No ML training",
    "No backtesting",
    "No signals",
    "No trading",
    "No writes through ArtifactClient",
    "None of these may be smuggled into any v0.7.0 PR",
    "verified readers remain trust boundaries",
    "explicit path only",
    "no hidden latest",
    "no current time",
    "no settings requirement for ArtifactClient",
    "no OpenD/network for ArtifactClient",
    "PyPI/TestPyPI deferred",
)
# Affirmative implementation / release claims that must never appear in
# the v0.7.0 direction document: PR-1 / PR-2 / PR-3 / PR-4 are merged
# history, PR-5 is the current (unmerged) stage, no later stage has
# started, and v0.7.0 is not released.
V070_DIRECTION_STALE_PHRASES = (
    "ArtifactClient is implemented",
    "ArtifactClient is available",
    "ArtifactClient() is implemented",
    "from market_vault import ArtifactClient",
    "PR-1: CURRENT",
    "PR-1: NOT STARTED",
    "PR-2: NOT STARTED",
    "PR-2: CURRENT",
    "PR-3: NOT STARTED",
    "PR-3: CURRENT",
    "PR-4: NOT STARTED",
    "PR-4: CURRENT",
    "PR-5: NOT STARTED",
    "PR-6: CURRENT",
    "V0.7.0 is released",
    "v0.7.0 has been released",
    "v0.7.0 released on",
)
# Facts the Python Client boundary contract must state: the PR-5
# integrated-status (including the exact formal delegation methods and
# their verified return / error types), the ArtifactClient root, the 13.x
# sections, the constructor contract, the exact PR-3 / PR-4 read methods
# and their formal delegation, the read-only scope, the trust boundary,
# the path contract, the read semantics, the return-value authority, the
# error boundary, the lightweight import, the absence of any Catalog
# convenience API, the explicit non-goals, and the PR-5 consumer-side
# usability boundary.
V070_CONTRACT_FACTS = (
    "# MarketVault Python Client Contract",
    "Status: PR-5 integrated acceptance/usability/examples in unreleased v0.7.0 development",
    "Target release: v0.7.0",
    "Public root: `ArtifactClient`",
    "Formal v0.6.1 GitHub Release artifacts",
    "DO NOT contain `ArtifactClient`",
    "package metadata remains 0.6.1",
    "frozen version policy",
    "## 13.1 Existing MarketVault compatibility",
    "the `MarketVault` constructor",
    "## 13.2 Constructor",
    "PR-2 foundation implemented",
    "Zero arguments",
    "Stateless",
    "## 13.3 Read-only scope",
    "## 13.4 Trust boundary",
    "## 13.5 Path contract",
    "## 13.6 Read semantics",
    "## 13.7 Return-value authority",
    "## 13.8 Error boundary",
    "## 13.9 Lightweight import",
    "## 13.10 Explicit non-goals",
    "PR-5: integrated acceptance/usability/examples CURRENT",
    "PR-6: release prep NOT STARTED",
    "package: 0.6.1",
    "v0.7.0: NOT RELEASED",
    "## 13.11 PR-5 consumer-side usability boundary",
    "CONSUMER-SIDE only",
    "second trust path",
    "Consumer transformations performed AFTER an ArtifactClient verified read",
    "are not artifact verification and are not part of",
    "the ArtifactClient trust contract",
    "No required settings",
    "No default settings path",
    "No implicit `config/settings.yaml`",
    "No filesystem access in the constructor",
    "No network",
    "No OpenD",
    "No current time",
    "No cwd-derived artifact root",
    "No build / materialize / generate / repair / write APIs",
    "`load_canonical_build`",
    "`load_dataset`",
    "`load_dataset_catalog`",
    "`load_verified_canonical_build`",
    "`load_verified_dataset`",
    "`load_verified_dataset_catalog`",
    "VerifiedCanonicalBuild",
    "VerifiedDatasetBuild",
    "VerifiedDatasetCatalogSnapshot",
    "DatasetCatalogArtifactValidationError",
    "No Catalog list convenience",
    "No Catalog show convenience",
    "No Catalog filter convenience",
    "No Catalog query convenience",
    "method-call boundary",
    "no client-side artifact parsing",
    "no client-side validation",
    "no exception wrapping",
    "parse `manifest.json` itself",
    "parse `catalog.json` itself",
    "second validation path",
    "repair artifacts",
    "rewrite artifacts",
    "delete artifacts",
    "adopt partial staging output",
    "`latest`",
    "auto-discovery",
    "environment-variable root",
    "settings-derived root",
    "cwd default root",
    "recursive scan",
    "search by guessing IDs",
    "Do not resolve symlinks to hide them",
    "mtime mutation",
    "cache file writes",
    "DuckDB Catalog construction",
    "No thin views",
    "second artifact-validation universe",
    "No warn-and-continue",
    "No partial success",
    "eagerly import `duckdb`, `pandas`, `moomoo`, or `futu`",
    "No REST API",
    "No API server",
    "No HTTP service",
    "No new CLI command",
    "No `dataset-catalog-query` CLI",
    "No ML training",
    "No model evaluation",
    "No experiment tracking",
    "No backtesting",
    "No signals",
    "No automatic trading",
    "No Trading Execution",
    "No new artifact format",
    "No identity v2",
    "No schema v2",
    "No migration",
    "No dependency modernization",
)
# Implemented claims that must never appear in the Python Client contract:
# only the PR-2 foundation and the PR-3 / PR-4 read methods are
# implemented; the full client is not, and the class implementation
# details are not contract state.
V070_CONTRACT_IMPLEMENTED_PHRASES = (
    "ArtifactClient is fully implemented",
    "ArtifactClient is available",
    "ArtifactClient() is implemented",
    "class ArtifactClient",
    "Implementation status: implemented",
)
# False read-capability claims that must never appear in the Python Client
# contract even when the required PR-4 markers are present: PR-2 never
# implemented any read access, PR-3 never implemented the Catalog read,
# and no Catalog convenience API exists.
V070_CONTRACT_FALSE_READ_CLAIMS = (
    "read access is implemented in PR-2",
    "PR-2 implements Canonical",
    "PR-2 implements Dataset",
    "PR-2 implements Catalog",
    "PR-3 implements Catalog",
    "PR-3 implements Dataset Catalog",
    "load_dataset_catalog is implemented in PR-3",
    "Catalog list convenience is implemented",
    "Catalog show convenience is implemented",
    "Catalog filter convenience is implemented",
    "Catalog query convenience is implemented",
)
# Facts the v0.7.0 existing Python API audit document must state: the
# audited top-level package behavior, the existing MarketVault
# constructor and method surface, the verified readers as formal trust
# boundaries, the compatibility finding, and the recommended
# settings-independent ArtifactClient architecture. The plan_backfill
# classification facts freeze the accurate local behavior: Catalog-backed
# local planning with no OpenD/network, using the current UTC date when
# today is omitted.
V070_AUDIT_FACTS = (
    "# MarketVault v0.7.0 Existing Python API Audit",
    "lazy",
    "`MarketVault`",
    "settings-backed",
    "plan_backfill",
    "local planning / read-local",
    "reads Catalog",
    "no OpenD/network",
    "uses current UTC date when today is omitted",
    "load_verified_canonical_build",
    "load_verified_dataset",
    "load_verified_dataset_catalog",
    "trust boundaries",
    "silently make settings optional",
    "compatibility surface",
    "public-name collision",
    "`ArtifactClient`",
)
# Stale or inaccurate plan_backfill claims that must never appear in the
# v0.7.0 Python API audit: plan_backfill is not "pure planning" and does
# not perform OpenD/network collection (only backfill does).
V070_AUDIT_STALE_PHRASES = (
    "pure planning",
    "performs OpenD",
)
# The v0.7.0 direction and contract documents must name the exact v0.7.0
# non-goals; these are checked as a second layer next to the direction
# facts.
V070_NONGOAL_MARKERS = (
    "REST API",
    "API server",
    "HTTP service",
    "dataset-catalog-query",
    "ML training",
    "backtesting",
    "signals",
    "automatic trading",
    "Trading Execution",
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
    if first_line.strip() != "# MarketVault v0.6.1":
        return [f"README first line is {first_line.strip()!r}, expected '# MarketVault v0.6.1'"]
    return []


def check_changelog(root: Path) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.exists():
        return ["CHANGELOG.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "## [0.6.1] - 2026-08-08" not in text:
        failures.append("CHANGELOG.md is missing '## [0.6.1] - 2026-08-08'")
    if "## [0.6.0] - 2026-08-08" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.6.0] - 2026-08-08'")
    if "## [0.5.1] - 2026-08-06" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.5.1] - 2026-08-06'")
    if "## [0.5.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.5.0] - 2026-08-05'")
    if "## [0.4.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.4.0] - 2026-08-05'")
    if "[0.6.1]: https://github.com/M0DIAN/market-vault/compare/v0.6.0...v0.6.1" not in text:
        failures.append("CHANGELOG.md is missing the v0.6.1 compare link")
    if "[0.6.0]: https://github.com/M0DIAN/market-vault/compare/v0.5.1...v0.6.0" not in text:
        failures.append("CHANGELOG.md no longer contains the v0.6.0 compare link")
    if "[0.5.1]: https://github.com/M0DIAN/market-vault/compare/v0.5.0...v0.5.1" not in text:
        failures.append("CHANGELOG.md no longer contains the v0.5.1 compare link")
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


def _v060_direction_current_state(text: str) -> str:
    # The current-state regions are the header (title, status, and intro,
    # up to the first planning section) and the Progress section. The
    # historical planning sections (Baseline, Goals, CLI direction,
    # non-goals, fixed PR sequence) describe the past and must not be
    # rejected for accurately quoting the preparation-time state.
    regions: list[str] = []
    if "## 1. Baseline" in text:
        regions.append(text.split("## 1. Baseline", 1)[0])
    if "## 8. Progress" in text:
        regions.append(text.split("## 8. Progress", 1)[1])
    return "\n".join(regions)


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
    current_state = _v060_direction_current_state(text)
    for phrase in V060_DIRECTION_STALE_PHRASES:
        if phrase in current_state:
            failures.append(
                "docs/v0_6_0_direction.md still contains the stale "
                f"wording {phrase!r}"
            )
    for claim in V060_DIRECTION_RELEASE_CLAIMS:
        if claim in text:
            failures.append(
                "docs/v0_6_0_direction.md contains the false release "
                f"claim {claim!r}"
            )
    for fact in V060_DIRECTION_PR8_FACTS:
        if fact not in text:
            failures.append(
                "docs/v0_6_0_direction.md does not state the PR-8 "
                f"progress fact {fact!r}"
            )
    for claim in V060_DIRECTION_PR8_FALSE_CLAIMS:
        if claim in text:
            failures.append(
                "docs/v0_6_0_direction.md contains the false PR-8 "
                f"claim {claim!r}"
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


def check_v060_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_6_0.md"
    if not path.exists():
        return ["docs/release_v0_6_0.md is missing"]
    text = path.read_text(encoding="utf-8")
    # Required facts are checked against the full document (several facts
    # live in the historical record), but stale current-state sentences are
    # checked only in the formal region before the historical
    # release-preparation record: the historical sections may quote the
    # preparation-time state verbatim.
    formal_text = text.split(HISTORICAL_RELEASE_PREPARATION_HEADER, 1)[0]
    failures = []
    for fact in RELEASE_V060_FACTS:
        if fact not in text:
            failures.append(
                f"docs/release_v0_6_0.md does not state the fact {fact!r}"
            )
    for phrase in RELEASE_V060_STALE_PHRASES:
        if phrase in formal_text:
            failures.append(
                f"docs/release_v0_6_0.md still contains the stale wording {phrase!r}"
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
    for phrase in SAMPLE_GENERATION_CONTRACT_STALE_PHRASES:
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
            # PR-7 registers the four Catalog commands in
            # dataset_catalog_cli.py; a hyphenated "dataset-catalog" string
            # in cli.py means an inline registration instead.
            failures.append(
                "top-level cli.py must never inline-register a Dataset "
                "Catalog command; registration goes through "
                "add_dataset_catalog_subparsers"
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
    for fact in DATASET_CATALOG_PR5_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"PR-5 fact {fact!r}"
            )
    for field in DATASET_CATALOG_FACTS_FIELDS:
        if field not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"exact facts field {field!r}"
            )
    for fact in DATASET_CATALOG_EXCLUDED_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"excluded fact {fact!r}"
            )
    for claim in DATASET_CATALOG_FALSE_IDENTITY_CLAIMS:
        if claim in text:
            failures.append(
                "docs/contracts/dataset_catalog.md contains the false "
                f"identity claim {claim!r}"
            )
    for claim in DATASET_CATALOG_PR5_FALSE_CLAIMS:
        if claim in text:
            failures.append(
                "docs/contracts/dataset_catalog.md contains the false "
                f"PR-5 claim {claim!r}"
            )
    if DATASET_CATALOG_REUSES_LEGACY_RE.search(text):
        failures.append(
            "docs/contracts/dataset_catalog.md claims the new Catalog "
            "reuses the legacy Catalog's tables"
        )
    for phrase in CONTRACT_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/contracts/dataset_catalog.md still contains the "
                f"stale claim {phrase!r}"
            )
    for phrase in DATASET_CATALOG_CONTRACT_STALE_PHRASES:
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


def check_dataset_catalog(root: Path) -> list[str]:
    """Static PR-5 checks: the three contract production modules exist, the
    exact version constants and public functions are defined, the modules
    never import the legacy Catalog, the dataset package exports the PR-5
    public API, and the formal contract document states the PR-5 facts and
    no false claim."""
    failures = []
    for rel in DATASET_CATALOG_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    models_path = root / "src" / "market_vault" / "dataset" / "dataset_catalog_models.py"
    if models_path.exists():
        text = models_path.read_text(encoding="utf-8")
        for version in DATASET_CATALOG_VERSION_CONSTANTS:
            if f'"{version}"' not in text:
                failures.append(
                    "dataset_catalog_models.py does not define the exact "
                    f"version constant {version!r}"
                )
        for marker in (
            "class DatasetCatalogDatasetFacts",
            "class DatasetCatalogObservedMetadata",
            "class DatasetCatalogEntry",
        ):
            if marker not in text:
                failures.append(
                    f"dataset_catalog_models.py is missing {marker}"
                )
        for marker in DATASET_CATALOG_HARDENING_MARKERS:
            if marker not in text:
                failures.append(
                    "dataset_catalog_models.py is missing the independent-"
                    f"review hardening marker {marker!r}"
                )
    identity_path = root / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    if identity_path.exists():
        text = identity_path.read_text(encoding="utf-8")
        for marker in ("def catalog_dataset_content_id", "def dataset_catalog_content_id"):
            if marker not in text:
                failures.append(
                    f"dataset_catalog_identity.py is missing {marker}"
                )
    projection_path = root / "src" / "market_vault" / "dataset" / "dataset_catalog_projection.py"
    if projection_path.exists():
        text = projection_path.read_text(encoding="utf-8")
        if "def project_dataset_catalog_entry" not in text:
            failures.append(
                "dataset_catalog_projection.py is missing "
                "project_dataset_catalog_entry"
            )
        if "VerifiedDatasetBuild" not in text:
            failures.append(
                "dataset_catalog_projection.py must bind the trust boundary "
                "to VerifiedDatasetBuild"
            )
    # The PR-5 modules must never import the legacy Catalog.
    for rel in DATASET_CATALOG_MODULES:
        path = root / rel
        if path.exists():
            text = path.read_text(encoding="utf-8")
            for forbidden in ("storage.catalog", "from market_vault.storage import Catalog"):
                if forbidden in text:
                    failures.append(
                        f"{rel} must never import the legacy Catalog "
                        f"({forbidden!r})"
                    )
    package = root / "src" / "market_vault" / "dataset" / "__init__.py"
    if package.exists():
        text = package.read_text(encoding="utf-8")
        for export in DATASET_CATALOG_EXPORTS:
            if export not in text:
                failures.append(
                    "market_vault.dataset does not export the PR-5 public "
                    f"API {export!r}"
                )
    failures.extend(check_dataset_catalog_contract(root))
    return failures


def check_dataset_catalog_pr6(root: Path) -> list[str]:
    """Static PR-6 checks: the eight production modules exist, the exact
    version constants and public functions are defined, the dataset
    package exports the PR-6 public API, the modules keep the fixed trust
    / identity / safety markers and stay free of the forbidden patterns
    (mutation guards for the builder trust boundary, the bounded scan,
    the content / snapshot identity separation, the reader no-reload
    contract, the _SUCCESS-last order, the no-overwrite publication, and
    the absence of ``latest``), the direction document records the PR-6
    stage and no false claim, and the CI fresh-wheel smoke covers the
    PR-6 public API imports."""
    failures = []
    for rel in DATASET_CATALOG_PR6_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    builder = root / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py"
    if builder.exists():
        text = builder.read_text(encoding="utf-8")
        if "def build_dataset_catalog" not in text:
            failures.append(
                "dataset_catalog_builder.py is missing build_dataset_catalog"
            )
        if "exactly one of dataset_root or candidate_build_dirs" not in text:
            failures.append(
                "dataset_catalog_builder.py must enforce the exactly-one "
                "input mode contract"
            )
    identity_path = (
        root / "src" / "market_vault" / "dataset" / "dataset_catalog_snapshot_identity.py"
    )
    if identity_path.exists():
        text = identity_path.read_text(encoding="utf-8")
        for version in (
            "market-vault-dataset-catalog-snapshot-v1",
            "market-vault-dataset-catalog-snapshot-manifest-v1",
            "market-vault-dataset-catalog-snapshot-id-v1",
            "market-vault-dataset-catalog-materializer-v1",
            "market-vault-verified-dataset-catalog-reader-v1",
        ):
            if f'"{version}"' not in text:
                failures.append(
                    "dataset_catalog_snapshot_identity.py does not define "
                    f"the exact version constant {version!r}"
                )
        if "def dataset_catalog_snapshot_id" not in text:
            failures.append(
                "dataset_catalog_snapshot_identity.py is missing "
                "dataset_catalog_snapshot_id"
            )
    builder_models = (
        root / "src" / "market_vault" / "dataset" / "dataset_catalog_builder_models.py"
    )
    if builder_models.exists():
        text = builder_models.read_text(encoding="utf-8")
        if f'"market-vault-dataset-catalog-builder-v1"' not in text:
            failures.append(
                "dataset_catalog_builder_models.py does not define the exact "
                "builder version constant "
                "'market-vault-dataset-catalog-builder-v1'"
            )
        for marker in ("class DatasetCatalogBuildError", "class DatasetCatalogBuildResult"):
            if marker not in text:
                failures.append(
                    f"dataset_catalog_builder_models.py is missing {marker}"
                )
    materialization = (
        root / "src" / "market_vault" / "dataset" / "dataset_catalog_materialization.py"
    )
    if materialization.exists():
        text = materialization.read_text(encoding="utf-8")
        if "def materialize_dataset_catalog_snapshot" not in text:
            failures.append(
                "dataset_catalog_materialization.py is missing "
                "materialize_dataset_catalog_snapshot"
            )
        # _SUCCESS must be written last: the staging verification precedes
        # the _SUCCESS write, and the _SUCCESS write precedes publication
        # (the calls are the indented call sites, never the def lines).
        success_index = text.index("    _write_empty_success(")
        if text.index("    _verify_staging_snapshot(") > success_index:
            failures.append(
                "dataset_catalog_materialization.py must verify the staging "
                "directory before _SUCCESS is written"
            )
        if success_index > text.index("raced = _publish_staging("):
            failures.append(
                "dataset_catalog_materialization.py must write _SUCCESS "
                "before the atomic publication"
            )
    reader = (
        root / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py"
    )
    if reader.exists():
        text = reader.read_text(encoding="utf-8")
        if "def load_verified_dataset_catalog" not in text:
            failures.append(
                "dataset_catalog_reader.py is missing "
                "load_verified_dataset_catalog"
            )
        if "def _second_pass_verify" not in text:
            failures.append(
                "dataset_catalog_reader.py is missing the second verification "
                "pass"
            )
    # Fixed trust / identity / safety markers.
    for rel, marker in (
        (builder, "load_verified_dataset(candidate)"),
        (builder, "project_dataset_catalog_entry(verified)"),
        (builder, "os.scandir(dataset_root)"),
        (reader, "historical observed location"),
        (reader, "never reloaded"),
        (materialization, "_atomic_rename_directory_no_replace(staging, final)"),
        (materialization, "type(written) is not int or written != len(data)"),
    ):
        if rel is not None and rel.exists():
            text = rel.read_text(encoding="utf-8")
            if marker not in text:
                failures.append(
                    f"{rel.name} is missing the contract marker {marker!r}"
                )
    # Forbidden patterns (mutation guards).
    for rel, patterns in DATASET_CATALOG_PR6_FORBIDDEN_PATTERNS.items():
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern in text:
                failures.append(
                    f"{rel} must not contain the forbidden pattern {pattern!r}"
                )
    # The dataset package exports the PR-6 public API.
    package = root / "src" / "market_vault" / "dataset" / "__init__.py"
    if package.exists():
        text = package.read_text(encoding="utf-8")
        for export in DATASET_CATALOG_PR6_EXPORTS:
            if export not in text:
                failures.append(
                    "market_vault.dataset does not export the PR-6 public "
                    f"API {export!r}"
                )
    # The formal contract document must state the explicit-absolute input
    # contract.
    contract = root / "docs" / "contracts" / "dataset_catalog.md"
    if contract.exists():
        text = contract.read_text(encoding="utf-8")
        for marker in DATASET_CATALOG_PR6_PATH_CONTRACT_MARKERS:
            if marker not in text:
                failures.append(
                    "docs/contracts/dataset_catalog.md does not state the "
                    f"builder path-contract marker {marker!r}"
                )
    # The direction document records the PR-6 stage and no false claim.
    direction = root / "docs" / "v0_6_0_direction.md"
    if direction.exists():
        text = direction.read_text(encoding="utf-8")
        for fact in V060_DIRECTION_PR6_FACTS:
            if fact not in text:
                failures.append(
                    "docs/v0_6_0_direction.md does not state the PR-6 "
                    f"progress fact {fact!r}"
                )
        for claim in V060_DIRECTION_PR6_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/v0_6_0_direction.md contains the false PR-6 "
                    f"claim {claim!r}"
                )
    # The CI fresh-wheel smoke covers the PR-6 public API imports.
    ci = root / ".github" / "workflows" / "ci.yml"
    if ci.exists():
        text = ci.read_text(encoding="utf-8")
        if CI_PR6_API_MARKER not in text:
            failures.append(
                f".github/workflows/ci.yml PR-6 public API smoke marker "
                f"{CI_PR6_API_MARKER!r} is missing"
            )
        for line in CI_PR6_API_IMPORT_LINES:
            if line not in text:
                failures.append(
                    f".github/workflows/ci.yml PR-6 smoke must import "
                    f"{line}"
                )
    return failures


def check_dataset_catalog_cli(root: Path) -> list[str]:
    """Static PR-7 checks: the two CLI production modules exist, the exact
    CLI version constants and the four command registrations are present,
    the CLI calls exactly the formal Builder -> Materializer -> Reader
    chain, the CLI keeps the forbidden patterns out (no fifth
    dataset-catalog-query command, no latest / force / overwrite, no
    settings loading, no legacy Catalog, no DuckDB, no Dataset reload, no
    raw catalog.json / manifest.json access), the top-level CLI dispatches
    the four commands before load_settings (settings-independent), the
    formal contract document states the Part C facts and no false claim,
    the direction document records the PR-7 stage and no false claim, and
    the CI fresh-wheel smoke covers the four help commands with the
    PR7_CATALOG_CLI_HELP_OK marker."""
    failures = []
    for rel in DATASET_CATALOG_CLI_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    cli_models = (
        root
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_cli_models.py"
    )
    if cli_models.exists():
        text = cli_models.read_text(encoding="utf-8")
        for version in DATASET_CATALOG_CLI_VERSION_CONSTANTS:
            if f'"{version}"' not in text:
                failures.append(
                    "dataset_catalog_cli_models.py does not define the exact "
                    f"CLI version constant {version!r}"
                )
        if "class DatasetCatalogCLIError" not in text:
            failures.append(
                "dataset_catalog_cli_models.py is missing "
                "DatasetCatalogCLIError"
            )
    cli_module = (
        root
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_cli.py"
    )
    if cli_module.exists():
        text = cli_module.read_text(encoding="utf-8")
        for command in DATASET_CATALOG_CLI_COMMANDS:
            if f'add_parser(\n        "{command}",' not in text:
                failures.append(
                    f"dataset_catalog_cli.py does not register {command}"
                )
        if '"dataset-catalog-query"' in text:
            failures.append(
                "dataset_catalog_cli.py must never register a fifth "
                "dataset-catalog-query command"
            )
        for function in DATASET_CATALOG_CLI_FUNCTIONS:
            if function not in text:
                failures.append(
                    "dataset_catalog_cli.py must call the formal function "
                    f"{function!r}"
                )
        for pattern in DATASET_CATALOG_CLI_FORBIDDEN_PATTERNS:
            if pattern in text:
                failures.append(
                    "dataset_catalog_cli.py must not contain the forbidden "
                    f"pattern {pattern!r}"
                )
    top_cli = root / "src" / "market_vault" / "cli.py"
    if top_cli.exists():
        text = top_cli.read_text(encoding="utf-8")
        for marker in (
            "add_dataset_catalog_subparsers",
            "DATASET_CATALOG_COMMANDS",
            "run_dataset_catalog_command",
        ):
            if marker not in text:
                failures.append(
                    "top-level cli.py is missing the Dataset Catalog CLI "
                    f"marker {marker!r}"
                )
        try:
            # The dispatch site is the ``if args.command in
            # DATASET_CATALOG_COMMANDS`` statement; the import at the top
            # of cli.py must never satisfy this ordering check.
            dispatch_index = text.index(
                "if args.command in DATASET_CATALOG_COMMANDS"
            )
            settings_index = text.index("load_settings(args.settings)")
        except ValueError:
            failures.append(
                "top-level cli.py must dispatch the Dataset Catalog commands "
                "before load_settings"
            )
        else:
            if dispatch_index > settings_index:
                failures.append(
                    "top-level cli.py must dispatch the Dataset Catalog "
                    "commands before load_settings (the dispatch marker "
                    "appears after the settings load)"
                )
    contract = root / "docs" / "contracts" / "dataset_catalog.md"
    if contract.exists():
        text = contract.read_text(encoding="utf-8")
        for fact in DATASET_CATALOG_CLI_CONTRACT_FACTS:
            if fact not in text:
                failures.append(
                    "docs/contracts/dataset_catalog.md does not state the "
                    f"PR-7 fact {fact!r}"
                )
        for claim in DATASET_CATALOG_CLI_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/contracts/dataset_catalog.md contains the false "
                    f"PR-7 claim {claim!r}"
                )
    direction = root / "docs" / "v0_6_0_direction.md"
    if direction.exists():
        text = direction.read_text(encoding="utf-8")
        for fact in V060_DIRECTION_PR7_FACTS:
            if fact not in text:
                failures.append(
                    "docs/v0_6_0_direction.md does not state the PR-7 "
                    f"progress fact {fact!r}"
                )
        for claim in V060_DIRECTION_PR7_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/v0_6_0_direction.md contains the false PR-7 "
                    f"claim {claim!r}"
                )
    ci = root / ".github" / "workflows" / "ci.yml"
    if ci.exists():
        text = ci.read_text(encoding="utf-8")
        if CI_PR7_API_MARKER not in text:
            failures.append(
                f".github/workflows/ci.yml PR-7 CLI help smoke marker "
                f"{CI_PR7_API_MARKER!r} is missing"
            )
        for command in CI_PR7_HELP_COMMANDS:
            if command not in text:
                failures.append(
                    ".github/workflows/ci.yml fresh-wheel smoke must cover "
                    f"'{command}'"
                )
    return failures


def check_v060_acceptance(root: Path) -> list[str]:
    """Static PR-8 checks for the v0.6.0 integrated acceptance document:
    the required fact markers are stated, the frozen static-reference
    values are recorded, no affirmative release claim appears, and no
    false cross-writer / provenance / PR-9 claim appears."""
    path = root / "docs" / "v0_6_0_acceptance.md"
    if not path.exists():
        return ["docs/v0_6_0_acceptance.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V060_ACCEPTANCE_FACTS:
        if fact not in text:
            failures.append(
                f"docs/v0_6_0_acceptance.md does not state the fact {fact!r}"
            )
    for claim in V060_ACCEPTANCE_FALSE_CLAIMS:
        if claim in text:
            failures.append(
                f"docs/v0_6_0_acceptance.md contains the false claim {claim!r}"
            )
    if V060_RELEASED_RE.search(text):
        failures.append(
            "docs/v0_6_0_acceptance.md contains the false claim "
            "'v0.6.0 is released'"
        )
    if FROZEN_FIXTURE_GENERATION_ID not in text:
        failures.append(
            "docs/v0_6_0_acceptance.md must record the frozen generation "
            "content id"
        )
    if FROZEN_RELATIVE_PLAN_SHA256 not in text:
        failures.append(
            "docs/v0_6_0_acceptance.md must record the frozen relative "
            "build-plan sha256"
        )
    return failures


def check_v060_frozen_fixture(root: Path) -> list[str]:
    """Static PR-8 mutation guards for the static reference artifact: the
    frozen identity values in the acceptance helpers must never change,
    and the base64 bundle + metadata JSON must keep existing at their
    exact frozen byte size."""
    helpers = root / "tests" / "v060_acceptance_helpers.py"
    bundle = (
        root / "tests" / "fixtures" / "v060_portability" / "canonical_fixture.b64"
    )
    metadata = (
        root / "tests" / "fixtures" / "v060_portability" / "fixture_metadata.json"
    )
    failures = []
    if not helpers.exists():
        return ["tests/v060_acceptance_helpers.py is missing"]
    text = helpers.read_text(encoding="utf-8")
    if FROZEN_FIXTURE_GENERATION_ID not in text:
        failures.append("the frozen FIXTURE_GENERATION_ID must not change")
    if FROZEN_RELATIVE_PLAN_SHA256 not in text:
        failures.append("the frozen FROZEN_RELATIVE_PLAN_SHA256 must not change")
    if FROZEN_FIXTURE_BUILD_ID not in text:
        failures.append("the frozen FIXTURE_BUILD_ID must not change")
    if not bundle.exists():
        failures.append(
            "tests/fixtures/v060_portability/canonical_fixture.b64 is missing"
        )
    elif (
        len(bundle.read_bytes().replace(b"\r\n", b"\n")) != FROZEN_BUNDLE_BYTE_SIZE
    ):
        failures.append("the static reference artifact bundle size must not change")
    if not metadata.exists():
        failures.append(
            "tests/fixtures/v060_portability/fixture_metadata.json is missing"
        )
    return failures


def check_pyarrow_dependency(root: Path) -> list[str]:
    """The supported PyArrow boundary is ``pyarrow>=16`` (never pinned to
    a writer version); the portability audit pins the audited writers only
    in the isolated CI job."""
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if '"pyarrow>=16"' not in text:
        failures.append("pyproject.toml must keep the pyarrow>=16 dependency")
    if re.search(r"pyarrow\s*==\s*\d", text):
        failures.append(
            "pyproject.toml must never pin a PyArrow writer version (pyarrow==)"
        )
    return failures


def check_ci_pr8(root: Path) -> list[str]:
    """The CI matrix stays exactly ``["3.11", "3.14"]``, the new
    ``portability-pyarrow24`` job installs ``pyarrow==24.0.0`` explicitly
    and runs the full offline suite under PyArrow 24.0.0, and the package
    job carries the ``PR8_INTEGRATED_ACCEPTANCE_OK`` marker."""
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if '"3.11", "3.14"' not in text:
        failures.append('CI python matrix must stay exactly ["3.11", "3.14"]')
    if "portability-pyarrow24" not in text:
        failures.append("CI is missing the portability-pyarrow24 job")
    if 'pip install "pyarrow==24.0.0"' not in text:
        failures.append(
            "CI portability-pyarrow24 job must install pyarrow==24.0.0"
        )
    if "PR8_INTEGRATED_ACCEPTANCE_OK" not in text:
        failures.append(
            "CI package job must carry the PR8_INTEGRATED_ACCEPTANCE_OK marker"
        )
    full_suite_step = "Run full offline suite under PyArrow 24.0.0"
    if full_suite_step not in text:
        failures.append(
            "CI portability-pyarrow24 job must include the full offline "
            "suite step (Run full offline suite under PyArrow 24.0.0)"
        )
    else:
        after = text.split(full_suite_step, 1)[1]
        if not re.search(r"(?m)^\s*run: python -m pytest\s*$", after[:400]):
            failures.append(
                "CI portability-pyarrow24 full-suite step must run "
                "python -m pytest"
            )
    return failures


def check_ci_v061_release_state(root: Path) -> list[str]:
    """The CI package job carries the ``V061_RELEASE_STATE_OK`` marker
    (the v0.6.1 released-state marker), the stale preparation marker
    ``V061_RELEASE_PREP_OK`` is never restored, the public API smoke
    imports ``generate_sample_requests``, and the wheel hygiene step
    forbids ``.b64`` files (the frozen static reference artifact fixture
    must never ship inside the wheel)."""
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if CI_V061_RELEASE_STATE_MARKER not in text:
        failures.append(
            "CI package job must carry the "
            f"{CI_V061_RELEASE_STATE_MARKER} marker"
        )
    if "V061_RELEASE_PREP_OK" in text:
        failures.append(
            "CI must never restore the stale V061_RELEASE_PREP_OK marker"
        )
    if "V061_RELEASED" in text:
        failures.append(
            "CI package job must never claim the V061_RELEASED state"
        )
    for import_line in CI_V061_PUBLIC_API_IMPORT_LINES:
        if import_line not in text:
            failures.append(
                f"CI public API smoke must import {import_line!r}"
            )
    if '".b64"' not in text:
        failures.append(
            "CI wheel hygiene forbidden tuple must include \".b64\""
        )
    return failures


def check_ci_v070_public_api_smoke(root: Path) -> list[str]:
    """The CI fresh-wheel smoke must exercise the PR-4 ArtifactClient
    surface (``from market_vault import ArtifactClient``, ``ArtifactClient()``,
    the three callable read methods), carry the
    ``V070_PUBLIC_API_IMPORT_OK`` marker, bind the Catalog client read in
    a fresh empty cwd, and carry the ``V070_CATALOG_CLIENT_IMPORT_OK``
    marker."""
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if CI_V070_PUBLIC_API_MARKER not in text:
        failures.append(
            "CI fresh-wheel smoke must carry the "
            f"{CI_V070_PUBLIC_API_MARKER} marker"
        )
    for line in CI_V070_PUBLIC_API_IMPORT_LINES:
        if line not in text:
            failures.append(
                f"CI fresh-wheel smoke must run {line}"
            )
    if CI_V070_CATALOG_CLIENT_MARKER not in text:
        failures.append(
            "CI fresh-wheel smoke must carry the "
            f"{CI_V070_CATALOG_CLIENT_MARKER} marker"
        )
    for line in CI_V070_CATALOG_CLIENT_IMPORT_LINES:
        if line not in text:
            failures.append(
                f"CI fresh-wheel Catalog client smoke must run {line}"
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


def check_readme_v061_section(root: Path) -> list[str]:
    """The README states the v0.6.1 maintenance section markers and the
    published-and-sealed release truth, and never contains the stale
    pre-release wording."""
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in README_V061_SECTION_MARKERS:
        if fact not in text:
            failures.append(
                f"README does not state the v0.6.1 maintenance fact {fact!r}"
            )
    for phrase in README_V061_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "README contains the stale v0.6.1 release-state "
                f"wording {phrase!r}"
            )
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
        if "market-vault 0.6.0" not in text:
            failures.append(
                "examples/dataset_cli/README.md does not state the install "
                "version 'market-vault 0.6.0'"
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


def check_v061_direction(root: Path) -> list[str]:
    """Static v0.6.1 direction checks: the document states the released
    status, the sealed 4-PR merge record, the formal release facts, the
    explicit non-goals, and the frozen invariants, and contains no stale
    pre-release wording and no false release claim."""
    path = root / "docs" / "v0_6_1_direction.md"
    if not path.exists():
        return ["docs/v0_6_1_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V061_DIRECTION_FACTS:
        if fact not in text:
            failures.append(
                f"docs/v0_6_1_direction.md does not state the fact {fact!r}"
            )
    for marker in V061_DIRECTION_NONGOAL_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_6_1_direction.md does not mark the v0.6.1 "
                f"non-goal {marker!r}"
            )
    for marker in V061_DIRECTION_INVARIANT_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_6_1_direction.md does not state the frozen "
                f"invariant {marker!r}"
            )
    for phrase in V061_DIRECTION_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/v0_6_1_direction.md still contains the stale "
                f"wording {phrase!r}"
            )
    for claim in V061_DIRECTION_FALSE_CLAIMS:
        if claim in text:
            failures.append(
                f"docs/v0_6_1_direction.md contains the false claim {claim!r}"
            )
    for claim in V061_DIRECTION_RELEASE_CLAIMS:
        if claim in text:
            failures.append(
                "docs/v0_6_1_direction.md contains the false release "
                f"claim {claim!r}"
            )
    return failures


def check_v061_release_notes(root: Path) -> list[str]:
    """The v0.6.1 release notes state the formal release status and facts,
    and never restore the release-preparation wording in the formal
    region. Required facts are checked against the full document (several
    facts live in the historical record, which quotes the
    preparation-time state verbatim), but stale current-state sentences
    are checked only in the formal region before the historical
    release-preparation record."""
    path = root / "docs" / "release_v0_6_1.md"
    if not path.exists():
        return ["docs/release_v0_6_1.md is missing"]
    text = path.read_text(encoding="utf-8")
    formal_text = text.split(HISTORICAL_RELEASE_PREPARATION_HEADER, 1)[0]
    failures = []
    for fact in V061_RELEASE_NOTES_FACTS:
        if fact not in text:
            failures.append(
                f"docs/release_v0_6_1.md does not state the fact {fact!r}"
            )
    for phrase in V061_RELEASE_NOTES_STALE_PHRASES:
        if phrase in formal_text:
            failures.append(
                "docs/release_v0_6_1.md formal region contains the stale "
                f"release claim {phrase!r}"
            )
    return failures


def check_v070_direction(root: Path) -> list[str]:
    """Static v0.7.0 direction checks: the document states the planned
    feature release status, the v0.6.1 baseline, the fixed 6-PR sequence
    with the exact stage names, the version rules, and the explicit
    non-goals, and contains no implemented-client or released-state
    claim."""
    path = root / "docs" / "v0_7_0_direction.md"
    if not path.exists():
        return ["docs/v0_7_0_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V070_DIRECTION_FACTS:
        if fact not in text:
            failures.append(
                f"docs/v0_7_0_direction.md does not state the fact {fact!r}"
            )
    for phrase in V070_DIRECTION_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/v0_7_0_direction.md contains the false "
                f"implementation/release claim {phrase!r}"
            )
    return failures


def check_v070_python_client_contract(root: Path) -> list[str]:
    """The Python Client boundary contract exists, states the PR-2
    foundation-implemented status, the ArtifactClient root, and the
    13.1-13.10 boundary clauses, contains no full-client implemented
    claim, and never claims Canonical / Dataset / Catalog read access is
    implemented by PR-2."""
    path = root / "docs" / "contracts" / "python_client.md"
    if not path.exists():
        return ["docs/contracts/python_client.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V070_CONTRACT_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/python_client.md does not state the "
                f"fact {fact!r}"
            )
    for marker in V070_NONGOAL_MARKERS:
        if marker not in text:
            failures.append(
                "docs/contracts/python_client.md does not mark the "
                f"v0.7.0 non-goal {marker!r}"
            )
    for phrase in V070_CONTRACT_IMPLEMENTED_PHRASES:
        if phrase in text:
            failures.append(
                "docs/contracts/python_client.md contains the false "
                f"implemented claim {phrase!r}"
            )
    for claim in V070_CONTRACT_FALSE_READ_CLAIMS:
        if claim in text:
            failures.append(
                "docs/contracts/python_client.md contains the false "
                f"PR-2 read-capability claim {claim!r}"
            )
    return failures


def check_v070_python_api_audit(root: Path) -> list[str]:
    """The v0.7.0 existing Python API audit document exists and states the
    audited top-level package behavior, the existing MarketVault surface,
    the verified readers as formal trust boundaries, the compatibility
    finding, and the recommended settings-independent ArtifactClient
    architecture."""
    path = root / "docs" / "v0_7_0_python_api_audit.md"
    if not path.exists():
        return ["docs/v0_7_0_python_api_audit.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V070_AUDIT_FACTS:
        if fact not in text:
            failures.append(
                "docs/v0_7_0_python_api_audit.md does not state the "
                f"fact {fact!r}"
            )
    for phrase in V070_AUDIT_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/v0_7_0_python_api_audit.md contains the stale "
                f"plan_backfill claim {phrase!r}"
            )
    return failures


def _check_artifact_client_module(module: Path) -> list[str]:
    """AST structural checks for the PR-4 ArtifactClient module: exactly
    one ``ArtifactClient`` class, the stateless ``__slots__ == ()``
    boundary, exactly the frozen method set (``__init__``,
    ``load_canonical_build``, ``load_dataset``, ``load_dataset_catalog``),
    a strict zero-argument ``__init__`` whose body performs no work, the
    exact reader method signatures, no try/except anywhere in the class,
    and no module import other than ``from __future__ import
    annotations``."""
    failures: list[str] = []
    try:
        tree = ast.parse(module.read_text(encoding="utf-8"))
    except SyntaxError:
        failures.append(f"{module.name} is not valid Python")
        return failures
    clients = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactClient"
    ]
    if len(clients) != 1:
        failures.append(
            f"{module.name} must define class ArtifactClient exactly once"
        )
        return failures
    cls = clients[0]
    methods = [
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    names = sorted(node.name for node in methods)
    if names != [
        "__init__",
        "load_canonical_build",
        "load_dataset",
        "load_dataset_catalog",
    ]:
        failures.append(
            "ArtifactClient public business methods must be exactly "
            "load_canonical_build, load_dataset and load_dataset_catalog, "
            "with only __init__ as constructor "
            f"(found: {', '.join(names)})"
        )
    if any(
        isinstance(node, ast.Try) for node in ast.walk(cls)
    ):
        failures.append(
            "ArtifactClient methods must not catch or wrap any exception "
            "(no try/except, formal errors propagate unwrapped)"
        )
    if not any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__slots__"
            for target in node.targets
        )
        and isinstance(node.value, ast.Tuple)
        and not node.value.elts
        for node in cls.body
    ):
        failures.append(
            "ArtifactClient must keep the stateless boundary __slots__ == ()"
        )
    inits = [node for node in methods if node.name == "__init__"]
    if len(inits) != 1:
        failures.append(
            "ArtifactClient must define exactly one __init__ method"
        )
    else:
        args = inits[0].args
        if (
            args.posonlyargs
            or len(args.args) != 1
            or args.args[0].arg != "self"
            or args.vararg is not None
            or args.kwarg is not None
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
        ):
            failures.append(
                "ArtifactClient.__init__ must take exactly self and no "
                "positional/keyword configuration arguments"
            )
        if not all(
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for node in inits[0].body
        ):
            failures.append(
                "ArtifactClient.__init__ body must not perform any work "
                "(no calls, no filesystem/network/time access)"
            )
    for method in methods:
        expected_args = {
            "load_canonical_build": ["self", "build_dir"],
            "load_dataset": ["self", "build_dir"],
            "load_dataset_catalog": ["self", "snapshot_dir"],
        }.get(method.name)
        if expected_args is not None:
            args = method.args
            if (
                args.posonlyargs
                or [arg.arg for arg in args.args] != expected_args
                or args.vararg is not None
                or args.kwarg is not None
                or args.kwonlyargs
                or args.defaults
                or args.kw_defaults
            ):
                failures.append(
                    f"ArtifactClient.{method.name} must take exactly "
                    f"({', '.join(expected_args)}) and no other arguments"
                )
    for node in tree.body:
        if isinstance(node, ast.Import):
            failures.append(
                "artifact_client.py must not import anything except "
                "__future__.annotations"
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module != "__future__" or not any(
                alias.name == "annotations" for alias in node.names
            ):
                failures.append(
                    "artifact_client.py must not import anything except "
                    "__future__.annotations"
                )
    return failures


# The exact formal reader delegation authority per ArtifactClient method:
# method name -> (relative reader module, formal reader function, the
# exact argument name the method passes through).
ARTIFACT_CLIENT_READER_DELEGATIONS = {
    "load_canonical_build": (
        ".canonical.reader",
        "load_verified_canonical_build",
        "build_dir",
    ),
    "load_dataset": (
        ".dataset.reader",
        "load_verified_dataset",
        "build_dir",
    ),
    "load_dataset_catalog": (
        ".dataset.dataset_catalog_reader",
        "load_verified_dataset_catalog",
        "snapshot_dir",
    ),
}
# Identifiers the ArtifactClient production source must never use outside
# docstrings: the client has no second trust path and no independent
# filesystem / manifest / json / hashing / resolution / discovery /
# settings / storage / network / write / repair / build access. Docstring
# constants are not ast.Name/ast.Attribute nodes, so documentation text
# is naturally excluded.
CLIENT_FORBIDDEN_IDENTIFIERS = (
    "Path",
    "open",
    "read_text",
    "read_bytes",
    "json",
    "hashlib",
    "resolve",
    "glob",
    "rglob",
    "walk",
    "scandir",
    "parquet",
    "pyarrow",
    "pandas",
    "environ",
    "settings",
    "config",
    "storage",
    "duckdb",
    "latest",
    "discover",
    "network",
    "OpenD",
    "requests",
    "urllib",
    "write",
    "repair",
    "materialize",
    "build",
)


def check_v070_artifact_client_readers(root: Path) -> list[str]:
    """PR-4 required checks: each ArtifactClient reader method delegates
    at the actual method-call boundary to the exact formal reader (a
    method-local import plus a direct return of the formal call on the
    method's own argument), and the client source contains no second
    trust path (no independent Path / open / json / hashlib / resolve /
    glob / walk / settings / config / latest / discover / network /
    requests / write / repair / materialize / build identifier use)."""
    failures: list[str] = []
    module = root / "src" / "market_vault" / "artifact_client.py"
    if not module.exists():
        failures.append("src/market_vault/artifact_client.py is missing")
        return failures
    text = module.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        failures.append(f"{module.name} is not valid Python")
        return failures
    clients = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactClient"
    ]
    if len(clients) != 1:
        failures.append(
            "src/market_vault/artifact_client.py must define class "
            "ArtifactClient exactly once"
        )
        return failures
    methods = {
        node.name: node
        for node in clients[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name, (reader_module, reader_func, arg_name) in (
        ARTIFACT_CLIENT_READER_DELEGATIONS.items()
    ):
        method = methods.get(name)
        if method is None:
            failures.append(
                f"ArtifactClient.{name} must exist and delegate to "
                f"{reader_func}"
            )
            continue
        statements = [
            node
            for node in method.body
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
        ]
        local_import = any(
            isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module == reader_module.lstrip(".")
            and [alias.name for alias in node.names] == [reader_func]
            for node in statements
        )
        direct_return = any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == reader_func
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == arg_name
            and not node.value.keywords
            for node in statements
        )
        if not local_import:
            failures.append(
                f"ArtifactClient.{name} must import {reader_func} from "
                f"{reader_module!r} at the method-call boundary"
            )
        if not direct_return:
            failures.append(
                f"ArtifactClient.{name} must return the direct "
                f"{reader_func}({arg_name}) result without wrapping"
            )
    for node in ast.walk(tree):
        identifier = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        if identifier in CLIENT_FORBIDDEN_IDENTIFIERS:
            failures.append(
                "ArtifactClient source must not independently use the "
                f"identifier {identifier!r} (no second trust path)"
            )
    return failures


def check_v070_artifact_client_catalog(root: Path) -> list[str]:
    """PR-4 required checks for the Dataset Catalog read: the
    ``load_dataset_catalog`` method exists, takes exactly ``(self,
    snapshot_dir)``, imports ``load_verified_dataset_catalog`` from the
    exact formal reader at the method-call boundary, returns the direct
    ``load_verified_dataset_catalog(snapshot_dir)`` result without
    wrapping, and performs no independent filesystem / manifest / json /
    hashing / discovery work of its own (no second trust path)."""
    failures: list[str] = []
    module = root / "src" / "market_vault" / "artifact_client.py"
    if not module.exists():
        failures.append("src/market_vault/artifact_client.py is missing")
        return failures
    text = module.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        failures.append(f"{module.name} is not valid Python")
        return failures
    clients = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactClient"
    ]
    if len(clients) != 1:
        failures.append(
            "src/market_vault/artifact_client.py must define class "
            "ArtifactClient exactly once"
        )
        return failures
    methods = {
        node.name: node
        for node in clients[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    method = methods.get("load_dataset_catalog")
    if method is None:
        failures.append(
            "ArtifactClient.load_dataset_catalog must exist and delegate "
            "to load_verified_dataset_catalog"
        )
        return failures
    args = method.args
    if (
        args.posonlyargs
        or [arg.arg for arg in args.args] != ["self", "snapshot_dir"]
        or args.vararg is not None
        or args.kwarg is not None
        or args.kwonlyargs
        or args.defaults
        or args.kw_defaults
    ):
        failures.append(
            "ArtifactClient.load_dataset_catalog must take exactly "
            "(self, snapshot_dir) and no other arguments"
        )
    statements = [
        node
        for node in method.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    local_import = any(
        isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "dataset.dataset_catalog_reader"
        and [alias.name for alias in node.names]
        == ["load_verified_dataset_catalog"]
        for node in statements
    )
    if not local_import:
        failures.append(
            "ArtifactClient.load_dataset_catalog must import "
            "load_verified_dataset_catalog from "
            "'.dataset.dataset_catalog_reader' at the method-call boundary"
        )
    direct_return = any(
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "load_verified_dataset_catalog"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "snapshot_dir"
        and not node.value.keywords
        for node in statements
    )
    if not direct_return:
        failures.append(
            "ArtifactClient.load_dataset_catalog must return the direct "
            "load_verified_dataset_catalog(snapshot_dir) result without "
            "wrapping"
        )
    for node in ast.walk(method):
        identifier = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        if identifier in CLIENT_FORBIDDEN_IDENTIFIERS:
            failures.append(
                "ArtifactClient.load_dataset_catalog must not independently "
                f"use the identifier {identifier!r} (no second trust path)"
            )
    return failures


def check_v070_artifact_client_foundation(root: Path) -> list[str]:
    """Required ArtifactClient checks: the module exists with the frozen
    structure (exactly one ArtifactClient class, ``__slots__ == ()``,
    exactly the frozen method set, a strict zero-argument side-effect-free
    ``__init__``, no module import besides ``__future__``), and the
    top-level package exports ArtifactClient lazily through ``__getattr__``
    (never through an eager top-level import) while keeping MarketVault
    and ``__version__`` in ``__all__``."""
    failures = []
    module = root / "src" / "market_vault" / "artifact_client.py"
    if not module.exists():
        failures.append("src/market_vault/artifact_client.py is missing")
    else:
        failures.extend(_check_artifact_client_module(module))
    init_path = root / "src" / "market_vault" / "__init__.py"
    if not init_path.exists():
        failures.append("src/market_vault/__init__.py is missing")
        return failures
    text = init_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        failures.append("src/market_vault/__init__.py is not valid Python")
        return failures
    for export in ("ArtifactClient", "MarketVault", "__version__"):
        if not any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            and isinstance(node.value, ast.List)
            and any(
                isinstance(elt, ast.Constant) and elt.value == export
                for elt in node.value.elts
            )
            for node in tree.body
        ):
            failures.append(
                "src/market_vault/__init__.py __all__ must contain "
                f"{export!r}"
            )
    if "def __getattr__" not in text:
        failures.append(
            "src/market_vault/__init__.py must define __getattr__ for the "
            "lazy public exports"
        )
    else:
        getattr_index = text.index("def __getattr__")
        lazy_import = "from .artifact_client import ArtifactClient"
        if lazy_import not in text:
            failures.append(
                "src/market_vault/__init__.py __getattr__ must lazily "
                "import ArtifactClient"
            )
        elif text.index(lazy_import) < getattr_index:
            failures.append(
                "ArtifactClient must be exported lazily through "
                "__getattr__, never through an eager top-level import"
            )
        if 'if name == "MarketVault":' not in text:
            failures.append(
                "src/market_vault/__init__.py __getattr__ must keep the "
                "lazy MarketVault branch"
            )
        if "from .api import MarketVault" not in text:
            failures.append(
                "src/market_vault/__init__.py __getattr__ must keep the "
                "lazy MarketVault import"
            )
    return failures


# Facts the v0.7.0 Python client usage document must state: the
# unreleased lifecycle, the exact three public business methods, the
# explicit-path contract, the formal delegation targets and verified
# return types, the Jupyter consumer-side post-verification boundary,
# the ML-consumer handoff with no ML implementation, and the existing
# formal error classes.
V070_USAGE_DOC_FACTS = (
    "unreleased v0.7",
    "0.6.1 through PR-5",
    "v0.7.0 is not released yet",
    "formal v0.6.1 GitHub Release artifacts do **NOT** contain",
    "Public business methods (exactly three):",
    "ArtifactClient.load_canonical_build(build_dir)",
    "ArtifactClient.load_dataset(build_dir)",
    "ArtifactClient.load_dataset_catalog(snapshot_dir)",
    "Every artifact path is EXPLICIT",
    "never looks up `latest`",
    "never scans or discovers artifacts",
    "never reads the current time",
    "load_verified_canonical_build",
    "load_verified_dataset",
    "load_verified_dataset_catalog",
    "VerifiedCanonicalBuild",
    "VerifiedDatasetBuild",
    "VerifiedDatasetCatalogSnapshot",
    "pd.DataFrame(dataset.rows",
    "verification happened BEFORE the DataFrame",
    "in-memory consumer representation",
    "not a second artifact verification path",
    "Do NOT parse",
    "dataset.parquet",
    "write back into the artifact directory",
    "does NOT train models",
    "automatic feature inference",
    "target inference",
    "train/test policy",
    "choose columns and splits EXPLICITLY",
    "NO sklearn / PyTorch / TensorFlow dependency",
    "CanonicalArtifactValidationError",
    "DatasetArtifactValidationError",
    "DatasetCatalogArtifactValidationError",
    "no ArtifactClient-specific error type",
)
# Discovery / settings / ML-implementation claims that must never appear
# in the v0.7.0 usage document: the client is explicit-path only and the
# guide contains no ML implementation code.
V070_USAGE_DOC_STALE_PHRASES = (
    "use the latest",
    "auto-discovery",
    "default artifact root",
    "discover the",
    "reads settings",
    "loads settings",
    "environment variable root",
    "model.fit(",
    "model.train(",
    "torch.",
    "tensorflow.",
    "sklearn.",
)
# Facts the PR-5 source-tree examples README must state: the example is
# consumer-side source-tree only, the unreleased lifecycle, the three
# explicit required path arguments, and the fail-closed boundaries.
V070_EXAMPLES_README_FACTS = (
    "source-tree",
    "not shipped as a public client API",
    "0.6.1 through PR-5",
    "v0.7.0 is not released yet",
    "--canonical-build-dir",
    "--dataset-build-dir",
    "--catalog-snapshot-dir",
    "looks up `latest`",
    "network or OpenD",
    "reads the current time",
    "parses `manifest.json`",
    "pandas or any ML / visualization framework",
    "verified readers remain the only trust boundaries",
    "Exit codes: 0 on success, 1 on any documented read failure",
    "The example never:",
)


def check_v070_python_client_usage_doc(root: Path) -> list[str]:
    """PR-5 required checks for the Python client usage document: it
    exists, states the unreleased lifecycle and the exact three business
    methods, documents the explicit-path contract, the Jupyter
    consumer-side post-verification boundary, the ML-consumer handoff
    with no ML implementation, and the existing formal error classes,
    and contains no discovery / settings / ML-implementation claim."""
    path = root / "docs" / "v0_7_0_python_client_usage.md"
    if not path.exists():
        return ["docs/v0_7_0_python_client_usage.md is missing"]
    # Collapse whitespace so markdown line wraps never break a phrase.
    text = " ".join(path.read_text(encoding="utf-8").split())
    failures = []
    for fact in V070_USAGE_DOC_FACTS:
        if " ".join(fact.split()) not in text:
            failures.append(
                "docs/v0_7_0_python_client_usage.md does not state the "
                f"fact {fact!r}"
            )
    for phrase in V070_USAGE_DOC_STALE_PHRASES:
        if " ".join(phrase.split()) in text:
            failures.append(
                "docs/v0_7_0_python_client_usage.md contains the false "
                f"discovery/ML claim {phrase!r}"
            )
    return failures


def check_v070_python_client_examples(root: Path) -> list[str]:
    """PR-5 required checks for the source-tree examples: the README
    exists and states the source-tree consumer-only facts and the three
    explicit required arguments, and the executable example registers
    exactly the three required path arguments with no defaults, calls
    the three ArtifactClient methods, prints one deterministic JSON
    object (``sort_keys=True``), and imports only stdlib plus the
    market_vault top level."""
    failures = []
    readme = root / "examples" / "python_client" / "README.md"
    if not readme.exists():
        failures.append("examples/python_client/README.md is missing")
    else:
        # Collapse whitespace so markdown line wraps never break a phrase.
        text = " ".join(readme.read_text(encoding="utf-8").split())
        for fact in V070_EXAMPLES_README_FACTS:
            if " ".join(fact.split()) not in text:
                failures.append(
                    "examples/python_client/README.md does not state the "
                    f"fact {fact!r}"
                )
    example = (
        root / "examples" / "python_client" / "read_verified_artifacts.py"
    )
    if not example.exists():
        failures.append(
            "examples/python_client/read_verified_artifacts.py is missing"
        )
        return failures
    source = example.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        failures.append(
            "examples/python_client/read_verified_artifacts.py is not "
            "valid Python"
        )
        return failures
    add_argument = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    names = [node.args[0].value for node in add_argument]
    if names != [
        "--canonical-build-dir",
        "--dataset-build-dir",
        "--catalog-snapshot-dir",
    ]:
        failures.append(
            "the example must register exactly the three required path "
            f"arguments, found {names}"
        )
    for node in add_argument:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        required = keywords.get("required")
        if not (
            isinstance(required, ast.Constant) and required.value is True
        ):
            failures.append(
                "each example path argument must be required=True"
            )
        if "default" in keywords:
            failures.append(
                "the example must not define default argument values"
            )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    for method in (
        "load_canonical_build",
        "load_dataset",
        "load_dataset_catalog",
    ):
        if method not in calls:
            failures.append(f"the example must call ArtifactClient.{method}")
    dumps = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dumps"
    ]
    if len(dumps) != 1:
        failures.append(
            "the example must print exactly one json.dumps object"
        )
    else:
        keywords = {kw.arg: kw.value for kw in dumps[0].keywords}
        sort_keys = keywords.get("sort_keys")
        if not (
            isinstance(sort_keys, ast.Constant) and sort_keys.value is True
        ):
            failures.append(
                "the example json.dumps must use sort_keys=True"
            )
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    if not imports <= {
        "__future__",
        "argparse",
        "json",
        "sys",
        "pathlib",
        "market_vault",
    }:
        failures.append(
            "the example must import only stdlib plus the market_vault "
            f"top level, found {sorted(imports)}"
        )
    return failures


def check_v061_cli_usability_audit(root: Path) -> list[str]:
    """The v0.6.1 PR-2 CLI usability audit document exists and states the
    audited baseline."""
    path = root / "docs" / "v0_6_1_cli_usability_audit.md"
    if not path.exists():
        return ["docs/v0_6_1_cli_usability_audit.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for marker in V061_CLI_USABILITY_AUDIT_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_6_1_cli_usability_audit.md does not state the "
                f"fact {marker!r}"
            )
    return failures


def check_ci_auditability(root: Path) -> list[str]:
    """The v0.6.1 PR-3 CI/package auditability guards: the GitHub Actions
    runtime majors moved to Node-24-capable versions (checkout v6,
    setup-python v6, upload-artifact v7, never the stale v4/v5 majors),
    the normal matrix stays exactly 3.11 + 3.14, the PyArrow24 CI pin stays
    exactly ``pyarrow==24.0.0`` with compatibility terminology (never the
    stale "writer" step labels), and the package audit chain (SHA256SUMS
    manifest, attempt-bound artifact name, fail-closed upload settings,
    and the V061_PACKAGE_AUDIT_OK marker) stays in place."""
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for action in ("actions/checkout@v6", "actions/setup-python@v6", "actions/upload-artifact@v7"):
        if action not in text:
            failures.append(f"CI must use the Node-24 Action major {action!r}")
    for stale in ("actions/checkout@v4", "actions/setup-python@v5"):
        if stale in text:
            failures.append(f"CI must never restore the stale Action major {stale!r}")
    if '"3.11", "3.14"' not in text:
        failures.append('CI python matrix must stay exactly ["3.11", "3.14"]')
    if 'pip install "pyarrow==24.0.0"' not in text:
        failures.append(
            "CI portability-pyarrow24 job must keep the exact pin pyarrow==24.0.0"
        )
    for stale_label in ("audited PyArrow 24.0.0 writer", "audited writer version"):
        if stale_label in text:
            failures.append(
                f"CI still contains the stale PyArrow step label {stale_label!r}"
            )
    for marker in (
        "SHA256SUMS.txt",
        "market-vault-package-${{ github.event.pull_request.head.sha || "
        "github.sha }}-attempt-${{ github.run_attempt }}",
        "if-no-files-found: error",
        "retention-days: 30",
        "overwrite: false",
        "V061_PACKAGE_AUDIT_OK",
        "V070_INTEGRATED_ACCEPTANCE_OK",
    ):
        if marker not in text:
            failures.append(f"CI package audit chain is missing {marker!r}")
    if (
        "market-vault-package-${{ github.sha }}-attempt-${{ "
        "github.run_attempt }}"
    ) in text:
        failures.append(
            "CI package artifact name regressed to github.sha-only naming "
            "(must bind github.event.pull_request.head.sha || github.sha)"
        )
    return failures


def check_v061_ci_package_audit(root: Path) -> list[str]:
    """The v0.6.1 PR-3 CI and package audit document exists and states the
    pinned baseline and the audit-chain markers."""
    path = root / "docs" / "v0_6_1_ci_package_audit.md"
    if not path.exists():
        return ["docs/v0_6_1_ci_package_audit.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for marker in V061_CI_PACKAGE_AUDIT_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_6_1_ci_package_audit.md does not state the "
                f"fact {marker!r}"
            )
    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [
        ("pyproject version", check_pyproject_version),
        ("package __version__", check_package_version),
        ("README title", check_readme_title),
        ("CHANGELOG entry", check_changelog),
        ("README wording", check_readme_no_stale_wording),
        ("README maintenance section", check_readme_maintenance_section),
        ("README v0.6.1 section", check_readme_v061_section),
        ("direction status", check_direction_status),
        ("release notes", check_release_notes),
        ("v0.5.1 release notes", check_v051_release_notes),
        ("v0.6.0 release notes", check_v060_release_notes),
        ("v0.5.1 direction", check_v051_direction),
        ("v0.6.0 direction", check_v060_direction),
        ("v0.6.1 direction", check_v061_direction),
        ("v0.6.1 release notes", check_v061_release_notes),
        ("v0.6.1 CLI usability audit", check_v061_cli_usability_audit),
        ("v0.7.0 direction", check_v070_direction),
        ("v0.7.0 Python client contract", check_v070_python_client_contract),
        ("v0.7.0 Python API audit", check_v070_python_api_audit),
        ("v0.7.0 ArtifactClient foundation", check_v070_artifact_client_foundation),
        ("v0.7.0 ArtifactClient readers", check_v070_artifact_client_readers),
        ("v0.7.0 ArtifactClient catalog", check_v070_artifact_client_catalog),
        ("v0.7.0 Python client usage doc", check_v070_python_client_usage_doc),
        ("v0.7.0 Python client examples", check_v070_python_client_examples),
        ("CI auditability", check_ci_auditability),
        ("v0.6.1 CI package audit", check_v061_ci_package_audit),
        ("v0.6.0 ADR", check_v060_adr),
        ("sample generation modules", check_sample_generation_modules),
        ("sample generation contract", check_sample_generation_contract),
        ("sample generator core", check_sample_generation_core),
        ("sample generation cli", check_sample_generation_cli),
        ("dataset catalog contract", check_dataset_catalog_contract),
        ("dataset catalog", check_dataset_catalog),
        ("dataset catalog pr6", check_dataset_catalog_pr6),
        ("dataset catalog cli", check_dataset_catalog_cli),
        ("v0.6.0 acceptance", check_v060_acceptance),
        ("v0.6.0 frozen fixture", check_v060_frozen_fixture),
        ("pyarrow dependency", check_pyarrow_dependency),
        ("CI PR-8 portability", check_ci_pr8),
        ("CI v0.6.1 release state", check_ci_v061_release_state),
        ("CI v0.7.0 public API smoke", check_ci_v070_public_api_smoke),
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
