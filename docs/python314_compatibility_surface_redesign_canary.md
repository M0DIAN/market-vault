# Python 3.14 Compatibility Surface — Redesign Canary (PR #74)

> **STATUS: PYTHON 3.14 COMPATIBILITY SURFACE REDESIGN — READY FOR INDEPENDENT REVIEW**
>
> MODE: MEASUREMENT / REDESIGN ONLY. No production Python 3.14 narrowing survives the
> final tree of this PR; production activation belongs to PR #75. **STOP BEFORE MERGE** —
> this PR is evidence, not activation.

- PR: https://github.com/M0DIAN/market-vault/pull/74
- Base: `07d3363927f9a76fe8deeae2a8349b1ca249f633` (origin/main, frozen)
- Temporary measurement head: `6197bc36d80b056821dc668b41a18f000ba69911`
  (exactly two temporary changes: `.github/workflows/ci.yml` measurement step +
  `ci/python314_compatibility_surface_redesign_canary.txt`; both reverted afterward)
- Final base→head diff of this PR: exactly one docs file (this report)

---

## 1. Design summary

The #73 canary retained 42 whole files / 3,340 of 3,807 nodes (87.7%) and was rejected
for activation as too broad. This redesign re-derives the 3.14 surface **per assertion**
under the §4 criterion: an assertion belongs on the 3.14 surface iff it could plausibly
fail on Python 3.14 while the same product behavior remains correct on Python 3.11,
because of interpreter, stdlib, ABI, dependency-wheel, import-system, filesystem,
timezone, serialization, CLI, or runtime compatibility differences.

The redesigned surface is a **compatibility surface, not a second product FULL**:

- It retains assertions that pin the **compatibility contract of the runtime and
  dependency boundary** — schema, dtype, tz-surfacing, SQL-engine behavior over parquet,
  import machinery, lazy-import guarantees, filesystem semantics (symlink/junction,
  os.replace/os.link), zoneinfo/DST rules, CLI-subprocess wiring, and literal committed
  identities.
- It does **not** retain assertions about product-semantic outputs whose expected values
  are produced by the same runtime over its own storage reads (audit completion,
  inventory counts, backfill plans, canonical-row identities, materialization manifests).
  Those are authoritative on the 3.11 FULL execution. Self-consistent in-process hashing
  never makes an assertion version-sensitive.

Resulting surface (all numbers measured against `FULL_COLLECTED = 3807`):

| Metric | #73 | #74 redesign |
|---|---|---|
| Manifest selectors | 42 files | 258 lines (2 whole + 256 nodes) |
| Resolved nodes | 3,340 | **294** |
| Collection share | 87.7% | **7.7%** |
| Files involved | 42 whole | 37 (2 whole, 35 partial) |
| Files dropped entirely | 0 | 14 |
| Reduction vs #73 | — | **91.2%** |

The historical 60–70% audit estimate was a file-level design reference, not a gate; the
node-level criterion of this redesign structurally produces a smaller share. The per-node
adjudication that produces every number in this report is documented below so an
independent reviewer can verify each exclusion. Section 12 shows the effect of the one
decision a reviewer might reverse (retaining the storage-era product-semantic clusters).

## 2. Ten cross-version contract families — explicit coverage map

Every selector below resolves on the candidate head (`6197bc3`, `python -m pytest
<manifest>`); the manifest itself is reproduced in Appendix A.

### 1. Import machinery / lazy import / public API
- `test_release_v061.py`: `test_import_market_vault_succeeds`, `test_import_does_not_load_moomoo`,
  `test_import_does_not_load_futu`, `test_import_does_not_load_duckdb`, `test_market_vault_remains_lazy`,
  `test_v061_public_api_imports_succeed`, `test_v061_public_api_imports_do_not_connect_opend`,
  `test_v061_public_api_imports_do_not_write_data`, `test_v061_dataset_exports_are_public`,
  `test_artifact_client_foundation_importable`, `test_version_in_all`
- `test_v070_artifact_client_foundation.py`: all 7 retained (top-level import, `__all__`,
  no-module-level-imports-besides-future, lazy import, empty-cwd constructor, method-local imports)
- `test_v070_artifact_client_catalog.py::test_catalog_method_binding_stays_lightweight_in_fresh_interpreter`
- `test_v070_artifact_client_readers.py`: 3 `*_method_call_boundary_loads_only_reader_chain`
- `test_v070_integrated_e2e.py::test_fresh_interpreter_import_and_binding_stays_lazy`
- `test_dataset_transform_registry.py::test_resolve_never_imports_transform_ref`,
  `test_import_has_no_registration_side_effects`, `test_path_and_mtime_absent_from_fingerprint`,
  `test_missing_source_rejected`, `test_public_api_exports`
- `test_dataset_feature_execution.py::test_no_filesystem_mtime_dependence`,
  `test_implementation_version_change_affects_pin`, `test_implementation_source_change_affects_pin`
- `test_chronological_splits.py`: `test_package_public_exports_include_the_split_api`,
  `test_public_exports_leak_no_private_helpers`, `test_existing_pit_and_dataset_exports_are_unchanged`,
  `test_split_layer_imports_or_executes_no_feature_or_label_transform`,
  `test_split_layer_never_touches_network_or_opend`
- `test_dataset_label_execution.py::test_public_api_surface`; `test_dataset_orchestration.py::test_public_api_exports`;
  `test_dataset_catalog_builder/materialization/reader.py::test_public_api_exports`;
  `test_sample_generation_core.py::test_core_public_exports_exact`;
  `test_sample_generation_contract.py::test_existing_public_exports_unchanged`;
  `test_feature_label_specs.py::test_public_all_stable_and_no_internal_leaks`;
  `test_sample_generation_cli.py::test_split_loader_is_the_single_shared_authority`

### 2. Filesystem / runtime semantics (symlink, junction, os.replace/os.link, relocation)
- `test_dataset_cli.py`: 6 symlink/junction fails-closed
- `test_dataset_materialization.py`: `test_linux_renameat2_errno_mapping`, `test_no_replace_dispatcher_unsupported_platform`,
  `test_no_replace_unavailable_fails_closed`, 7 symlink/junction fails-closed, 4 rename-race
- `test_verified_dataset_reader.py`: 13 symlink/junction fails-closed,
  `test_mtime_change_does_not_affect_identity`, `test_relocation_passes_and_identity_stable`
- `test_dataset_manifest_core.py`: 9 `test_atomic_write_*` (os.link)
- `test_dataset_catalog_builder.py`: `test_root_is_symlink_fails`, `test_root_ancestor_symlink_fails`,
  `test_root_mode_rejects_64hex_symlink`
- `test_dataset_catalog_reader.py::test_symlinked_artifact_fails` (3 params),
  `test_snapshot_directory_symlink_fails`
- `test_v060_integrated_e2e.py`: 4 `test_security_symlinked_*_fails_closed`
- `test_sample_generation_cli.py`: `test_plan_rejects_symlinked_plan`, `test_output_symlink_fails`
- `test_dataset_catalog_cli.py::test_build_rejects_symlink_candidate`
- `test_canonical_materialization_v03.py`: 2 manifest-symlink fails-closed
- `test_pit_sample_assembly.py::test_symlinked_file_fails`
- `test_dataset_catalog_contract.py::test_relocated_dataset_keeps_content_id`,
  `test_projection_never_reads_the_build_directory`
- `test_feature_label_specs.py::test_parse_never_touches_filesystem`

### 3. Timezone / zoneinfo / DST / local-time independence
- `test_timestamp_semantics_v03.py`: 8 retained (incl. `test_utc_conversion_across_seasons` (2 params),
  `test_duckdb_round_trip_surfaces_session_timezone` (2 params), `test_parquet_round_trip_preserves_timezone`)
- `test_dataset_end_to_end_regression.py`: 7 `test_e2e_timezone_*`
- `test_verified_dataset_reader.py`: `test_dst_spring_forward_boundary_case`, `test_dst_fall_back_boundary_case`,
  `test_local_timezone_change_does_not_affect_result`, `test_model_built_at_normalized_equivalent_representation`
- `test_chronological_splits.py`: 10 zoneinfo/DST/`tzset`-adjacent nodes
- `test_leakage_threat_model.py`: 7 `test_timezone_*`
- `test_pit_sample_assembly.py::test_equivalent_utc_and_non_utc_representations_identical`
- `test_dataset_feature_execution.py::test_local_timezone_independence`, `test_no_current_time_dependence`
- `test_dataset_transform_registry.py::test_no_timezone_dependence`
- `test_normalization.py::test_normalize_assigns_timezones_and_sessions`
- `test_dataset_manifest_core.py::test_timezone_equivalent_dataset_as_of_same_id`
- `test_canonical_builder_v03.py`: 3 tz-representation nodes
- `test_dataset_catalog_contract.py::test_timezone_equivalent_datetime_same_identity`
- `test_intraday_audit_v03.py`: 3 tz-offset serialization nodes (literal `-04:00` / `-05:00`)
- `test_dataset_cli.py`: 6 renderer datetime-semantics nodes

### 4. Frozen cross-version identity (literal committed digests / static artifacts)
- `test_sample_generation_core.py::test_identity_frozen_fixture` (literal FIXTURE_GENERATION_ID
  reproduction over the committed PyArrow-25 static fixture)
- `test_chronological_splits.py::test_valid_content_ids_are_pinned_and_unchanged`
- `test_dataset_manifest_core.py`: 6 literal serialization pins (IEEE-754 binary64, tagged forms,
  negative zero, microsecond timestamps, unicode normalization, deterministic JSON bytes)
- `test_sample_generation_cli.py::test_relative_fixture_build_plan_bytes_unchanged_from_old_head`
- `test_v060_integrated_e2e.py::test_matrix_a_generation_identical_across_roots`

### 5. CLI / subprocess wiring (real `python -m market_vault`)
- `test_release_v061.py`: `test_cli_version_output`, `test_cli_version_does_not_require_settings_file`,
  `test_cli_version_does_not_require_subcommand`, `test_cli_version_exit_zero`,
  `test_cli_top_level_help_lists_all_commands`, `test_each_subcommand_help_parses` (15 commands),
  `test_help_and_version_do_not_construct_collectors`, `test_dataset_cli_helps_do_not_require_settings`
- `test_v060_integrated_e2e.py`: `test_complete_chain_all_six_cli_steps`, `test_empty_chain_through_catalog`,
  `test_matrix_b_dataset_identity_cwd_and_location_independent`
- `test_sample_generation_cli.py`: `test_complete_e2e`, `test_empty_e2e`, `test_cwd_independence_subprocess`,
  `test_sample_generate_works_without_settings_file`, `test_plan_accepts_relative_path_from_cwd`
- `test_dataset_catalog_cli.py::test_catalog_commands_work_without_settings_file`
- `test_v070_integrated_e2e.py::test_example_execution_against_real_chain`

### 6. Binary / runtime dependency interaction (pyarrow, duckdb, NumPy, pandas)
- `test_canonical_reader.py` (WHOLE, 3) — pyarrow partition/schema inference over static fixtures;
  the module docstring documents cross-version partition-merge failures
- `test_deprecation_compatibility_v051.py` (WHOLE, 5) — NumPy/API deprecation contracts (family 7 shared)
- `test_calendar_v03.py`: 5 duckdb-view nodes (SQL engine over parquet, Python `date` read-back)
- `test_options_v02.py`: 3 duckdb-view nodes
- `test_snapshot_safety.py`: 2 nodes (legacy parquet read-back, force-recollect SQL)
- `test_timestamp_semantics_v03.py::test_duckdb_round_trip_surfaces_session_timezone` (2 params),
  `test_parquet_round_trip_preserves_timezone`
- `test_dataset_materialization.py`: 8 arrow/pyarrow nodes (`test_arrow_type_mapping`,
  `test_parquet_schema_of_materialized_build`, `test_parquet_metadata_exact`, error-chain nodes,
  corrupt-parquet nodes, `test_null_label_value_in_parquet`)
- `test_verified_dataset_reader.py`: 25 parquet read-back nodes (schema, dtype, metadata, scalar
  types, dictionary rejection, `test_rederived_schema_exact`, `test_schema_field_order_and_types`,
  `test_second_parquet`)
- `test_canonical_materialization_v03.py`: `test_parquet_explicit_column_order_and_types`,
  `test_parquet_utc_round_trip_and_null_optionals`
- `test_dataset_end_to_end_regression.py`: `test_e2e_corrupted_parquet_arbitrary_bytes_rejected`,
  `test_e2e_non_finite_label_nan_inf_fails_closed`, `test_e2e_non_finite_label_catalog_boundary_fails_closed`
- `test_dataset_manifest_core.py`: `test_int64_accepts_numpy_integers`, `test_int64_boundaries_accepted`
- `test_feature_label_specs.py::test_parameter_value_types_fail_closed` (NumPy scalars)
- `test_v070_artifact_client_catalog.py::test_catalog_client_read_matches_direct_formal_reader`;
  `test_v070_artifact_client_readers.py`: 3 `*_client_read_matches_direct_reader`
- `test_normalization.py::test_normalize_assigns_timezones_and_sessions` (pandas tz assignment)

### 7. Active deprecation / compatibility contracts
- `test_deprecation_compatibility_v051.py` (WHOLE, 5)

### 8. PIT / leakage / snapshot safety
- `test_pit_sample_assembly.py`: 2 nodes
- `test_leakage_threat_model.py`: 7 timezone/clock/leakage nodes
- `test_snapshot_safety.py`: 2 nodes

### 9. Representative deep end-to-end integration
- `test_v060_integrated_e2e.py::test_complete_chain_all_six_cli_steps` (six-command subprocess chain)
- `test_dataset_end_to_end_regression.py`: 10 nodes (tz cluster + corrupt-parquet + non-finite)
- `test_v070_integrated_e2e.py::test_example_execution_against_real_chain`

### 10. Current v0.7 ArtifactClient / package / public API behavior
- `test_v070_artifact_client_foundation.py` (7), `test_v070_artifact_client_catalog.py` (2),
  `test_v070_artifact_client_readers.py` (6), `test_v070_integrated_e2e.py` (2),
  `test_release_v061.py::test_artifact_client_foundation_importable`

## 3. Per-file disposition — all 51 test files

Disposition keys: **WHOLE** = whole file on the 3.14 surface; **PARTIAL** = only the listed
selectors; **DROP** = 3.11 FULL is the authoritative product-correctness execution (§4).

| File | Disp. | Retained | Compatibility failure mode | Why 3.11 FULL is/is not sufficient | Relation to #73 |
|---|---|---|---|---|---|
| test_release_v061.py | PARTIAL (19) | §2 families 1/5/10 list | CLI/subprocess, import machinery, lazy-import, `--help`/`--version` source-tree wiring | NOT sufficient (subprocess + import machinery are interpreter-dependent) | #73 whole (452). Kept the exact §6.3 list; dropped version facts, static exit-code assertions, checker mutation matrix, docs/changelog assertions |
| test_v060_integrated_e2e.py | PARTIAL (8) | §2 families 2/4/5/9 | deep E2E subprocess chain, literal identity, symlink fails-closed | NOT sufficient | #73 whole. Same 8 |
| test_sample_generation_cli.py | PARTIAL (9) | §2 families 1/2/4/5 | import is-identity, CLI subprocess, symlink fails-closed, frozen plan bytes | NOT sufficient | #73 whole. Dropped version-constant and argparse-shape tests (in-process, version-stable) |
| test_dataset_catalog_cli.py | PARTIAL (2) | symlink candidate, no-settings subprocess | symlink, subprocess wiring | NOT sufficient | #73 whole |
| test_dataset_cli.py | PARTIAL (12) | 6 symlink/junction + 6 renderer datetime | symlink/junction; datetime serialization in fresh subprocess | NOT sufficient | #73 whole (148). Dropped renderer wording/exit-code/argparse shape (docs-layer, version-stable) and builder logic |
| test_v070_integrated_e2e.py | PARTIAL (2) | fresh-interpreter lazy import, example chain | import machinery, subprocess | NOT sufficient | #73 whole |
| test_dataset_end_to_end_regression.py | PARTIAL (10) | 7 tz + corrupt-parquet + 2 non-finite | zoneinfo DST rules, pyarrow read-back, NaN/Inf dtype handling | NOT sufficient | #73 whole (96). Dropped chain canaries (IEEE float math), archive/purge logic |
| test_v070_artifact_client_foundation.py | PARTIAL (7) | §2 family 1 list | import machinery, lazy loading, package boundaries | NOT sufficient | #73 whole |
| test_v070_artifact_client_catalog.py | PARTIAL (2) | fresh-interpreter binding, read parity | lazy binding, duckdb/parquet read parity | NOT sufficient | #73 whole |
| test_v070_artifact_client_readers.py | PARTIAL (6) | 3 boundary + 3 read-parity | import boundary, parquet read parity | NOT sufficient | #73 whole |
| test_snapshot_safety.py | PARTIAL (2) | legacy-file read, force-recollect | duckdb/parquet read-back contract | NOT sufficient | #73 whole |
| test_options_v02.py | PARTIAL (3) | 3 duckdb-view nodes | SQL engine over parquet | NOT sufficient | #73 whole |
| test_dataset_materialization.py | PARTIAL (26) | §2 families 2/6 list | ctypes syscall ABI + errno, os.replace semantics, symlink/junction, arrow type mapping | NOT sufficient | #73 whole (143). Dropped build-plan logic and manifest facts (in-process) |
| test_dataset_feature_execution.py | PARTIAL (5) | §2 families 1/3 list | clock/runtime independence, module-machinery mtime | NOT sufficient | #73 whole |
| test_dataset_transform_registry.py | PARTIAL (8) | §2 families 1/3 list | import machinery, registration side-effects, fingerprint without mtime/path | NOT sufficient | #73 whole |
| test_dataset_manifest_core.py | PARTIAL (20) | §2 families 2/4/6 list | os.link atomic-write, literal serialization forms, int64 boundaries, path semantics | NOT sufficient | #73 whole (128). Dropped tamper-rejection/change-detection (self-consistent in-run) |
| test_feature_label_specs.py | PARTIAL (6) | §2 families 1/2/6 list | import boundary, filesystem absence, BOM/NFC text semantics | NOT sufficient | #73 whole |
| test_dataset_label_execution.py | PARTIAL (1) | `test_public_api_surface` | `__all__` pin | NOT sufficient | #73 whole; 4 weak datetime-boundary tests dropped |
| test_verified_dataset_reader.py | PARTIAL (44) | 13 symlink/junction + 4 tz + 25 parquet + mtime + relocation | symlink/junction, tz-surfacing, parquet schema/dtype/metadata read-back | NOT sufficient (parquet read-back is the wheel contract) | #73 whole (235). Dropped tamper envelope, diagnostics math, spec-artifact checks, canonical-byte validation |
| test_chronological_splits.py | PARTIAL (16) | §2 families 1/3/4 list | zoneinfo DST rules, literal content-id digests, import machinery | NOT sufficient | #73 whole (139). Dropped split assignment/purge logic |
| test_dataset_catalog_builder.py | PARTIAL (4) | `__all__` + 3 symlink | import boundary, symlink | NOT sufficient | #73 whole |
| test_dataset_catalog_materialization.py | PARTIAL (1) | `test_public_api_exports` | import boundary | NOT sufficient | #73 whole |
| test_dataset_catalog_reader.py | PARTIAL (3) | `__all__` + 2 symlink | import boundary, symlink | NOT sufficient | #73 whole |
| test_canonical_materialization_v03.py | PARTIAL (4) | 2 parquet + 2 symlink | parquet schema/UTC round-trip, symlink | NOT sufficient | #73 whole |
| test_timestamp_semantics_v03.py | PARTIAL (8) | §2 family 3 list | zoneinfo DST, duckdb tz-surfacing | NOT sufficient | #73 whole |
| test_calendar_v03.py | PARTIAL (5) | 5 duckdb-view nodes | SQL engine over parquet | NOT sufficient | #73 whole; dropped collector/normalization logic and repo-hygiene importlib node |
| test_pit_sample_assembly.py | PARTIAL (2) | tz-representation identity, symlink fails-closed | tz identity, symlink | NOT sufficient | #73 whole |
| test_leakage_threat_model.py | PARTIAL (7) | 7 `test_timezone_*` | tz/clock leakage into captured output | NOT sufficient | #73 whole |
| test_canonical_builder_v03.py | PARTIAL (3) | 3 tz-representation | zoneinfo tz semantics | NOT sufficient (tz machinery); the other 57 nodes are self-consistent in-run identities (#73 §2.4 reasoning) | #73 whole. 11 PYD candidates adjudicated; 9 dropped as self-consistent |
| test_dataset_orchestration.py | PARTIAL (1) | `test_public_api_exports` | import boundary | NOT sufficient | #73 whole |
| test_dataset_catalog_contract.py | PARTIAL (3) | relocation identity, build-dir read prohibition, tz-equivalent identity | relocation + identity, zoneinfo representation | NOT sufficient | #73 whole |
| test_sample_generation_core.py | PARTIAL (2) | frozen-fixture identity, `__all__` | literal identity over static artifact | NOT sufficient | #73 whole |
| test_sample_generation_contract.py | PARTIAL (1) | `test_existing_public_exports_unchanged` | `__all__` pin | NOT sufficient | #73 whole; BASE_IDENTITY/PIT_SAMPLE_KEY constants dropped (deterministic recompute over in-process constants, not runtime-derived) |
| test_normalization.py | PARTIAL (1) | tz/session assignment | pandas tz semantics | NOT sufficient | #73 whole |
| test_intraday_audit_v03.py | PARTIAL (3) | 3 tz-offset serialization (literal `-04:00`/`-05:00`) | zoneinfo DST offset rules | NOT sufficient (zoneinfo); SQL structure/gap/overall clusters are product semantics over storage reads | #73 whole (129) |
| test_deprecation_compatibility_v051.py | WHOLE (5) | whole file | active deprecation/API contracts | NOT sufficient (contracts must be re-proven per runtime) | #73 whole. Same |
| test_canonical_reader.py | WHOLE (3) | whole file | pyarrow partition/schema inference | NOT sufficient (documented cross-version partition-merge failures) | #73 whole. Same |
| test_ci_risk_tier.py | DROP | — | — | IS sufficient: control-plane contract established P1-2 as 3.11-only (§6.1) | #73 whole |
| test_component_aware_tiers.py | DROP | — | — | IS sufficient: control-plane (§6.1) | #73 whole |
| test_ci_post_merge_reuse.py | DROP | — | — | IS sufficient: control-plane (§6.1); sys.modules hits are a static importlib loading mechanism, not a module-machinery assertion | #73 whole |
| test_audit_pr.py | DROP | — | — | IS sufficient: control-plane (§6.1) | #73 whole |
| test_v061_ci_auditability.py | DROP | — | — | IS sufficient (§6.1). Only DIGEST candidate pins a 40-hex literal in audit-doc **text** — a docs/release-policy assertion, not runtime output | #73 whole |
| test_v060_portability.py | DROP | — | — | IS sufficient: meaningful environment is the pinned PyArrow24 portability job, which already executes this file (§6.2); frozen-SHA facts are asserted there. Frozen-identity family covered by sample_generation_core / chronological / manifest_core pins | #73 whole |
| test_audit_v03.py | DROP | — | — | IS sufficient: assertions pin audit completion/coverage/reason semantics — product behavior over the storage stack; expected values are product-semantic, not wheel-boundary contracts. The stack's wheel contract is covered by the retained pins (calendar/options/snapshot_safety/timestamp_semantics duckdb, canonical_reader/verified_reader/materialization parquet) | #73 whole |
| test_backfill_v03.py | DROP | — | — | IS sufficient: same line (plan decisions/counts = product semantics over storage) | #73 whole |
| test_inventory_v03.py | DROP | — | — | IS sufficient: same line (inventory counts/completions = product semantics over storage) | #73 whole |
| test_collector.py | DROP | — | — | IS sufficient: in-process collector logic, version-independent | #73 whole |
| test_quality.py | DROP | — | — | IS sufficient: in-process quality logic, version-independent | #73 whole |
| test_moomoo_sdk.py | DROP | — | — | IS sufficient: fake-object loader, no real runtime boundary | #73 whole |
| test_v070_python_client_examples.py | DROP | — | — | IS sufficient: static doc/AST assertions, no runtime execution | #73 whole |
| test_v061_cli_usability.py | DROP | — | — | IS sufficient: all in-process argparse assertions; no subprocess/filesystem/module machinery. The audit §9 file-level heuristic is superseded by the node-level reading | #73 whole |

Totals: **WHOLE 2 files / 8 nodes; PARTIAL 35 files / 256 selectors; DROP 14 files / 0 nodes.**

## 4. Node-set proof (measured on `6197bc3`, local Python 3.14.4, pytest 9.1.1)

| Quantity | Value |
|---|---|
| PY314_SELECTOR_COUNT | 258 (2 whole-file + 256 node selectors) |
| WHOLE / PARTIAL files | 2 / 35 |
| PY314_RESOLVED_NODE_COUNT | **294** (every selector resolves; 0 duplicates) |
| PY314_RESOLVED_NODE_SHA256 | `7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58` |
| FULL_COLLECTED | 3807 |
| PY314_COLLECTION_SHARE | 294/3807 = **7.7%** |
| PR73_NODE_COUNT | 3340 |
| NODES_REMOVED_VS_PR73 | 3054 |
| NODES_ADDED_VS_PR73 | 8 (all documented below) |
| REDUCTION_VS_PR73_PERCENT | **91.2%** |

Newly added nodes (8) and justification — every one is a §4-sensitive node #73 missed by
whole-file inclusion or by prior exclusion reasoning:

1. `test_canonical_builder_v03.py::test_session_timezone_cannot_alter_identities` — zoneinfo tz-representation semantics
2. `test_canonical_builder_v03.py::test_same_key_same_instant_different_tz_not_conflict` — zoneinfo tz-representation semantics
3. `test_canonical_builder_v03.py::test_ranking_independent_of_local_timezone_representation` — zoneinfo tz-representation semantics
4. `test_dataset_catalog_contract.py::test_projection_never_reads_the_build_directory` — filesystem boundary (family 2)
5. `test_dataset_catalog_contract.py::test_relocated_dataset_keeps_content_id` — relocation identity (families 2/4)
6. `test_dataset_catalog_contract.py::test_timezone_equivalent_datetime_same_identity` — zoneinfo representation (family 3)
7. `test_dataset_orchestration.py::test_public_api_exports` — import boundary (family 1)
8. `test_normalization.py::test_normalize_assigns_timezones_and_sessions` — pandas tz assignment (family 6)

## 5. Local validation (pre-flight, before the measurement commit)

- Full collect-only: 3807 nodes. Candidate collect-only: 294 nodes, 0 duplicate resolved IDs.
- High-risk smoke (candidate run locally on 3.14.4): **278 passed, 16 skipped, 0 failed in 62.57s**.
  All 16 skips are environment-dependent (Windows dev box: symlink/junction unavailable in
  temp dirs, `time.tzset` unavailable) — the documented audit §17 category; they execute on
  the Linux runner (7 skips there).
- `python scripts/check_release.py` → `RELEASE_CHECK_OK version=0.7.0` (before and after the
  temporary workflow step).
- `python scripts/check_repo_hygiene.py` → passed. `git diff --check` → clean.

## 6. CI attempt 1 (run `31450636807`, attempt 1, head `6197bc3`)

All 4 formal jobs **success**:

| Job | Job seconds |
|---|---|
| test (3.11) | 252 |
| test (3.14) | **325** |
| portability-pyarrow24 | 117 |
| package | 57 |
| **Raw workflow wall** | **385** |

3.14-leg steps (from job step timestamps and log):

| Step | Step wall | pytest |
|---|---|---|
| Measure redesigned Python 3.14 compatibility surface (candidate) | 66s | **62.71s** — 287 passed, 7 skipped |
| Run offline tests (FULL) | 223s | **223.20s** — 3800 passed, 7 skipped |

On-runner classifier: `tier=full`, `full_matrix_required=true`. Package job:
`RELEASE_CHECK_OK version=0.7.0`. V1 attestation artifact created for attempt 1
with exactly: `schema_version=1, pr_number=74, base_sha=07d3363927f9a76fe8deeae2a8349b1ca249f633,
head_sha=6197bc36d80b056821dc668b41a18f000ba69911, tier=full, full_matrix_required=true`
— **no V2 fields**.

## 7. CI attempt 2 (run `31450636807`, attempt 2 — same exact head, no new commit)

All 4 formal jobs **success**:

| Job | Job seconds |
|---|---|
| test (3.11) | 243 |
| test (3.14) | **337** |
| portability-pyarrow24 | 106 |
| package | 58 |
| **Raw workflow wall** | **398** |

3.14-leg steps:

| Step | Step wall | pytest |
|---|---|---|
| Measure redesigned Python 3.14 compatibility surface (candidate) | 66s | **65.51s** — 287 passed, 7 skipped |
| Run offline tests (FULL) | 242s | **240.75s** — 3800 passed, 7 skipped |

On-runner classifier: `tier=full`, `full_matrix_required=true`. Package job:
`RELEASE_CHECK_OK version=0.7.0`. V1 attestation for attempt 2 with the same exact fields.

## 8. TWO-RUN OBSERVED RANGE and the A/B/C savings model

(Two runs on the exact same head; all timings are step-level from GitHub timestamps and
pytest's own summary lines. In both attempts the candidate ran before FULL, so FULL may be
slightly warmed → measured replacement saving is conservative. Label for the wall model:
**MODELLED / NOT PRODUCTION-MEASURED** — the workflow wall is not measured with the
narrowed 3.14 job, it is modelled from the observed job/step times.)

| Quantity | Attempt 1 | Attempt 2 | TWO-RUN OBSERVED RANGE |
|---|---|---|---|
| Candidate pytest | 62.71s | 65.51s | **62.71–65.51s** |
| Candidate step wall | 66s | 66s | **66s** |
| FULL pytest (3.14) | 223.20s | 240.75s | **223.20–240.75s** |
| FULL step wall (3.14) | 223s | 242s | **223–242s** |
| 3.14 job | 325s | 337s | 325–337s |
| 3.11 job | 252s | 243s | 243–252s |
| portability | 117s | 106s | 106–117s |
| package | 57s | 58s | 57–58s |
| workflow wall | 385s | 398s | 385–398s |

A/B/C model (per §20):

| Quantity | Attempt 1 | Attempt 2 |
|---|---|---|
| TEST314_TEMP_JOB_SECONDS | 325 | 337 |
| CANDIDATE_STEP_WALL_SECONDS | 66 | 66 |
| FULL_STEP_WALL_SECONDS | 223 | 242 |
| MODELLED_CURRENT_314_JOB (= 325/337 − 66) | 259 | 271 |
| MODELLED_NARROWED_314_JOB (= 325/337 − 242) | 102 | 95 |
| A_JOB_LOCAL_SAVING = B_RUNNER_SAVING | **157s** | **176s** |
| CURRENT_MODEL = max(3.11, CURRENT_314, portability) + package | max(252,259,117)+57 = 316 | max(243,271,106)+58 = 329 |
| NARROWED_MODEL = max(3.11, NARROWED_314, portability) + package | max(252,102,117)+57 = 309 | max(243,95,106)+58 = 301 |
| C_MODELLED_WALL_SAVING | 7s | 28s |

## 9. Comparison vs #73 (primary empirical baseline)

| Quantity | #73 | #74 redesign | Verdict |
|---|---|---|---|
| Surface size | 42 files, 3340 nodes (87.7%) | 37 files, 294 nodes (7.7%) | **materially smaller (91.2% reduction)** |
| Candidate pytest (range) | 183.97–196.98s | **62.71–65.51s** | **≈65% smaller** |
| Candidate step wall | 186–199s | 66s | materially better |
| FULL pytest (range) | 226.08–236.30s | 223.20–240.75s | equivalent |
| Runner saving (A = B) | 38–40s | **157–176s** | **≈4.2× better** |
| Modelled wall saving (C) | 0–22s | 7–28s | better / comparable |
| 3.14 job | 442–468s | 325–337s | ≈26% faster |
| 3.11 job | 247–259s | 243–252s | unchanged (FULL authority intact) |
| portability / package | 104–164s / 57–59s | 106–117s / 57–58s | unchanged |
| FULL evidence | 2 exact-head runs, V1 attestation | 2 exact-head runs, V1 attestation per attempt | equal rigor |

Exclusion reasoning in this redesign is never "this test is slow" — every one of the 3,513
dropped-vs-FULL nodes is covered by the §4 line documented per file in Section 3 (product
semantics authoritative on 3.11 FULL vs. wheel-boundary contract retained on 3.14).

## 10. Reviewer dial — the one reversible decision

The storage-era cluster (audit_v03, backfill_v03, inventory_v03, most of intraday_audit_v03
and canonical_builder_v03) was adjudicated as **product-semantic outputs over the storage
stack** (expected values are hard-coded but produced by the same runtime's own
duckdb/parquet reads) → dropped; the wheel-boundary of that stack is pinned by the retained
duckdb/parquet nodes. A reviewer who prefers retaining the full storage-era clusters would
add ≈250 nodes (surface ≈545 nodes, ≈14.3%; runner saving ≈130–150s) — still a 3.5×
reduction vs #73's surface, but the present report adopts the stricter reading that the
3.14 surface is a compatibility surface, not a second product FULL.

## 11. Recommendation: **A — REDESIGNED SURFACE SUITABLE FOR INDEPENDENT ACTIVATION REVIEW**

All §25 conditions for A are met:

1. Every family mapped to retained selectors → Section 2 (10/10 families)
2. Explicit disposition + reason for all 51 files → Section 3
3. Exact auditable selectors → Appendix A (258-line manifest; committed on temp head `6197bc3`)
4. No unresolved or duplicate nodes → Section 4 (294 resolved, 0 duplicates)
5. Two exact-head candidate PASSes → attempts 1+2 (287 passed / 7 env-skips both)
6. Two exact-head FULL PASSes → attempts 1+2 (3800 passed / 7 env-skips both)
7. Candidate materially smaller than #73 → 294 vs 3340 nodes; 62.7–65.5s vs 184–197s
8. Runner saving materially better than #73 → 157–176s vs 38–40s
9. Exclusion reasoning never "this test is slow" → Section 3 per-file reasons
10. 3.11 remains FULL authority → unchanged `Run offline tests` on 3.11
11. Checker / PyArrow24 portability / V1 attestation unchanged → verified; no changes to
    `scripts/check_release.py`, `scripts/ci_risk_tier.py`, `scripts/ci_post_merge_reuse.py`,
    `ci/components.toml`, tests, src, V1 contract
12. No V2 attestation fields → attestations are schema_version=1 only

This recommendation is **NOT activation approval**. Production activation of the narrowed
3.14 surface is PR #75 and requires independent review of this evidence.

---

## Appendix A — Manifest (as committed on temp head `6197bc3`)

`ci/python314_compatibility_surface_redesign_canary.txt`, 258 non-comment lines, one exact
pytest selector per line, sorted deterministically, no `-k`/`-m`/globs/directories/dynamic
discovery/substring matching, no duplicates, no node selector from a WHOLE file:

```text
tests/test_calendar_v03.py::test_calendar_latest_partial_range_snapshot_leaves_outside_old_rows
tests/test_calendar_v03.py::test_calendar_latest_supports_old_parquet_without_requested_range
tests/test_calendar_v03.py::test_calendar_latest_withdraws_dates_missing_from_new_covering_snapshot
tests/test_calendar_v03.py::test_calendar_paths_and_duckdb_latest_use_captured_at
tests/test_calendar_v03.py::test_calendar_query_no_files_returns_empty
tests/test_canonical_builder_v03.py::test_ranking_independent_of_local_timezone_representation
tests/test_canonical_builder_v03.py::test_same_key_same_instant_different_tz_not_conflict
tests/test_canonical_builder_v03.py::test_session_timezone_cannot_alter_identities
tests/test_canonical_materialization_v03.py::test_manifest_symlinked_file_fails
tests/test_canonical_materialization_v03.py::test_manifest_symlinked_partition_dir_fails
tests/test_canonical_materialization_v03.py::test_parquet_explicit_column_order_and_types
tests/test_canonical_materialization_v03.py::test_parquet_utc_round_trip_and_null_optionals
tests/test_canonical_reader.py
tests/test_chronological_splits.py::test_boundaries_are_never_constructed_with_fixed_24h_deltas
tests/test_chronological_splits.py::test_equivalent_timezone_representations_give_identical_results
tests/test_chronological_splits.py::test_existing_pit_and_dataset_exports_are_unchanged
tests/test_chronological_splits.py::test_fall_back_next_local_midnight_is_correct
tests/test_chronological_splits.py::test_feature_close_uses_declared_timezone_local_date
tests/test_chronological_splits.py::test_invalid_timezone_is_rejected
tests/test_chronological_splits.py::test_microsecond_precision_is_normalized
tests/test_chronological_splits.py::test_package_public_exports_include_the_split_api
tests/test_chronological_splits.py::test_public_exports_leak_no_private_helpers
tests/test_chronological_splits.py::test_split_layer_imports_or_executes_no_feature_or_label_transform
tests/test_chronological_splits.py::test_split_layer_never_touches_network_or_opend
tests/test_chronological_splits.py::test_spring_forward_next_local_midnight_is_correct
tests/test_chronological_splits.py::test_timezone_equivalent_feature_closes_normalize_identically
tests/test_chronological_splits.py::test_timezone_has_no_system_local_fallback
tests/test_chronological_splits.py::test_utc_date_and_market_local_date_diverge_at_boundaries
tests/test_chronological_splits.py::test_valid_content_ids_are_pinned_and_unchanged
tests/test_dataset_catalog_builder.py::test_public_api_exports
tests/test_dataset_catalog_builder.py::test_root_ancestor_symlink_fails
tests/test_dataset_catalog_builder.py::test_root_is_symlink_fails
tests/test_dataset_catalog_builder.py::test_root_mode_rejects_64hex_symlink
tests/test_dataset_catalog_cli.py::test_build_rejects_symlink_candidate
tests/test_dataset_catalog_cli.py::test_catalog_commands_work_without_settings_file
tests/test_dataset_catalog_contract.py::test_projection_never_reads_the_build_directory
tests/test_dataset_catalog_contract.py::test_relocated_dataset_keeps_content_id
tests/test_dataset_catalog_contract.py::test_timezone_equivalent_datetime_same_identity
tests/test_dataset_catalog_materialization.py::test_public_api_exports
tests/test_dataset_catalog_reader.py::test_public_api_exports
tests/test_dataset_catalog_reader.py::test_snapshot_directory_symlink_fails
tests/test_dataset_catalog_reader.py::test_symlinked_artifact_fails
tests/test_dataset_cli.py::test_build_rejects_junction_plan
tests/test_dataset_cli.py::test_build_rejects_symlinked_plan
tests/test_dataset_cli.py::test_build_rejects_symlinked_plan_parent
tests/test_dataset_cli.py::test_feature_spec_symlink_rejected
tests/test_dataset_cli.py::test_label_spec_symlink_rejected
tests/test_dataset_cli.py::test_renderer_accepts_timezone_aware_dataset_as_of
tests/test_dataset_cli.py::test_renderer_fixed_six_digit_microseconds
tests/test_dataset_cli.py::test_renderer_normalizes_built_at_to_utc
tests/test_dataset_cli.py::test_renderer_parser_datetime_semantics_unchanged
tests/test_dataset_cli.py::test_renderer_rejects_naive_built_at
tests/test_dataset_cli.py::test_renderer_rejects_naive_dataset_as_of
tests/test_dataset_cli.py::test_spec_parent_junction_rejected
tests/test_dataset_end_to_end_regression.py::test_e2e_corrupted_parquet_arbitrary_bytes_rejected
tests/test_dataset_end_to_end_regression.py::test_e2e_non_finite_label_catalog_boundary_fails_closed
tests/test_dataset_end_to_end_regression.py::test_e2e_non_finite_label_nan_inf_fails_closed
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_dst_fall_back_boundary
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_dst_spring_forward_boundary
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_equivalent_representations_same_identity
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_invalid_iana_fails_closed
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_split_uses_declared_local_date
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_tz_env_no_effect
tests/test_dataset_end_to_end_regression.py::test_e2e_timezone_utc_microsecond_output
tests/test_dataset_feature_execution.py::test_implementation_source_change_affects_pin
tests/test_dataset_feature_execution.py::test_implementation_version_change_affects_pin
tests/test_dataset_feature_execution.py::test_local_timezone_independence
tests/test_dataset_feature_execution.py::test_no_current_time_dependence
tests/test_dataset_feature_execution.py::test_no_filesystem_mtime_dependence
tests/test_dataset_label_execution.py::test_public_api_surface
tests/test_dataset_manifest_core.py::test_atomic_write_default_mode_does_not_overwrite_raced_destination
tests/test_dataset_manifest_core.py::test_atomic_write_idempotent_accepts_identical_bytes
tests/test_dataset_manifest_core.py::test_atomic_write_idempotent_race_different_content_fails
tests/test_dataset_manifest_core.py::test_atomic_write_idempotent_race_same_content_passes
tests/test_dataset_manifest_core.py::test_atomic_write_idempotent_rejects_conflicting_content
tests/test_dataset_manifest_core.py::test_atomic_write_injected_link_failure_publishes_nothing
tests/test_dataset_manifest_core.py::test_atomic_write_injected_write_failure_cleans_temp
tests/test_dataset_manifest_core.py::test_atomic_write_refuses_existing_destination
tests/test_dataset_manifest_core.py::test_atomic_write_success
tests/test_dataset_manifest_core.py::test_deterministic_json_with_trailing_newline
tests/test_dataset_manifest_core.py::test_explicit_tagged_formats_pinned
tests/test_dataset_manifest_core.py::test_float_uses_fixed_ieee754_binary64_encoding
tests/test_dataset_manifest_core.py::test_int64_accepts_numpy_integers
tests/test_dataset_manifest_core.py::test_int64_boundaries_accepted
tests/test_dataset_manifest_core.py::test_negative_zero_normalizes
tests/test_dataset_manifest_core.py::test_timestamp_microseconds_normalized
tests/test_dataset_manifest_core.py::test_timezone_equivalent_dataset_as_of_same_id
tests/test_dataset_manifest_core.py::test_unicode_normalization_pinned
tests/test_dataset_manifest_core.py::test_unsafe_output_paths_fail
tests/test_dataset_manifest_core.py::test_windows_drive_and_ads_paths_fail
tests/test_dataset_materialization.py::test_arrow_array_error_wrapped_at_public_boundary
tests/test_dataset_materialization.py::test_arrow_error_not_double_wrapped
tests/test_dataset_materialization.py::test_arrow_schema_field_order_and_nullability
tests/test_dataset_materialization.py::test_arrow_table_construction_error_wrapped_at_public_boundary
tests/test_dataset_materialization.py::test_arrow_type_mapping
tests/test_dataset_materialization.py::test_corruption_final_symlink
tests/test_dataset_materialization.py::test_corruption_missing_parquet
tests/test_dataset_materialization.py::test_corruption_nested_symlink
tests/test_dataset_materialization.py::test_corruption_truncated_parquet
tests/test_dataset_materialization.py::test_corruption_wrong_parquet_schema
tests/test_dataset_materialization.py::test_linux_renameat2_errno_mapping
tests/test_dataset_materialization.py::test_no_replace_dispatcher_unsupported_platform
tests/test_dataset_materialization.py::test_no_replace_unavailable_fails_closed
tests/test_dataset_materialization.py::test_null_label_value_in_parquet
tests/test_dataset_materialization.py::test_output_root_junction_rejected
tests/test_dataset_materialization.py::test_output_root_junction_with_valid_existing_dataset_rejected
tests/test_dataset_materialization.py::test_output_root_symlink_rejected
tests/test_dataset_materialization.py::test_output_root_symlink_with_valid_existing_dataset_rejected
tests/test_dataset_materialization.py::test_parquet_metadata_exact
tests/test_dataset_materialization.py::test_parquet_schema_of_materialized_build
tests/test_dataset_materialization.py::test_preexisting_staging_symlink_fails
tests/test_dataset_materialization.py::test_pyarrow_error_wrapped
tests/test_dataset_materialization.py::test_race_empty_final_before_publish_precheck_path
tests/test_dataset_materialization.py::test_race_empty_final_before_publish_rejected
tests/test_dataset_materialization.py::test_rename_race_corrupt_final_fails
tests/test_dataset_materialization.py::test_rename_race_valid_identical_final
tests/test_dataset_orchestration.py::test_public_api_exports
tests/test_dataset_transform_registry.py::test_crlf_lf_normalization_equivalence
tests/test_dataset_transform_registry.py::test_import_has_no_registration_side_effects
tests/test_dataset_transform_registry.py::test_missing_source_rejected
tests/test_dataset_transform_registry.py::test_no_timezone_dependence
tests/test_dataset_transform_registry.py::test_path_and_mtime_absent_from_fingerprint
tests/test_dataset_transform_registry.py::test_public_api_exports
tests/test_dataset_transform_registry.py::test_resolve_never_imports_transform_ref
tests/test_dataset_transform_registry.py::test_unicode_string_literal_normalization_does_not_collide
tests/test_deprecation_compatibility_v051.py
tests/test_feature_label_specs.py::test_bom_rejected
tests/test_feature_label_specs.py::test_load_rejects_bom_and_invalid_utf8
tests/test_feature_label_specs.py::test_nfc_equivalent_text_hashes_identically
tests/test_feature_label_specs.py::test_parameter_value_types_fail_closed
tests/test_feature_label_specs.py::test_parse_never_touches_filesystem
tests/test_feature_label_specs.py::test_public_all_stable_and_no_internal_leaks
tests/test_intraday_audit_v03.py::test_gap_times_use_market_time_with_offset
tests/test_intraday_audit_v03.py::test_segment_times_use_market_time_with_offset
tests/test_intraday_audit_v03.py::test_segment_times_winter_offset_minus_five
tests/test_leakage_threat_model.py::test_timezone_dst_fall_back_boundary_local_calendar
tests/test_leakage_threat_model.py::test_timezone_dst_spring_forward_boundary_local_calendar
tests/test_leakage_threat_model.py::test_timezone_equivalent_as_of_same_version_id
tests/test_leakage_threat_model.py::test_timezone_equivalent_instants_identical_identities
tests/test_leakage_threat_model.py::test_timezone_invalid_iana_fails_closed
tests/test_leakage_threat_model.py::test_timezone_no_system_local_fallback
tests/test_leakage_threat_model.py::test_timezone_split_uses_declared_local_date_not_utc_date
tests/test_normalization.py::test_normalize_assigns_timezones_and_sessions
tests/test_options_v02.py::test_option_paths_and_duckdb_latest_view
tests/test_options_v02.py::test_option_volatility_latest_view_uses_captured_at_before_run_id
tests/test_options_v02.py::test_option_volatility_parquet_and_duckdb_include_analysis
tests/test_pit_sample_assembly.py::test_equivalent_utc_and_non_utc_representations_identical
tests/test_pit_sample_assembly.py::test_symlinked_file_fails
tests/test_release_v061.py::test_artifact_client_foundation_importable
tests/test_release_v061.py::test_cli_top_level_help_lists_all_commands
tests/test_release_v061.py::test_cli_version_does_not_require_settings_file
tests/test_release_v061.py::test_cli_version_does_not_require_subcommand
tests/test_release_v061.py::test_cli_version_exit_zero
tests/test_release_v061.py::test_cli_version_output
tests/test_release_v061.py::test_dataset_cli_helps_do_not_require_settings
tests/test_release_v061.py::test_each_subcommand_help_parses
tests/test_release_v061.py::test_help_and_version_do_not_construct_collectors
tests/test_release_v061.py::test_import_does_not_load_duckdb
tests/test_release_v061.py::test_import_does_not_load_futu
tests/test_release_v061.py::test_import_does_not_load_moomoo
tests/test_release_v061.py::test_import_market_vault_succeeds
tests/test_release_v061.py::test_market_vault_remains_lazy
tests/test_release_v061.py::test_v061_dataset_exports_are_public
tests/test_release_v061.py::test_v061_public_api_imports_do_not_connect_opend
tests/test_release_v061.py::test_v061_public_api_imports_do_not_write_data
tests/test_release_v061.py::test_v061_public_api_imports_succeed
tests/test_release_v061.py::test_version_in_all
tests/test_sample_generation_cli.py::test_complete_e2e
tests/test_sample_generation_cli.py::test_cwd_independence_subprocess
tests/test_sample_generation_cli.py::test_empty_e2e
tests/test_sample_generation_cli.py::test_output_symlink_fails
tests/test_sample_generation_cli.py::test_plan_accepts_relative_path_from_cwd
tests/test_sample_generation_cli.py::test_plan_rejects_symlinked_plan
tests/test_sample_generation_cli.py::test_relative_fixture_build_plan_bytes_unchanged_from_old_head
tests/test_sample_generation_cli.py::test_sample_generate_works_without_settings_file
tests/test_sample_generation_cli.py::test_split_loader_is_the_single_shared_authority
tests/test_sample_generation_contract.py::test_existing_public_exports_unchanged
tests/test_sample_generation_core.py::test_core_public_exports_exact
tests/test_sample_generation_core.py::test_identity_frozen_fixture
tests/test_snapshot_safety.py::test_force_recollect_does_not_overwrite_old_snapshots
tests/test_snapshot_safety.py::test_legacy_market_bars_file_without_run_id_still_readable
tests/test_timestamp_semantics_v03.py::test_ambiguous_dst_time_raises
tests/test_timestamp_semantics_v03.py::test_dst_transition_dates_convert_correctly
tests/test_timestamp_semantics_v03.py::test_duckdb_round_trip_surfaces_session_timezone
tests/test_timestamp_semantics_v03.py::test_nonexistent_dst_time_raises
tests/test_timestamp_semantics_v03.py::test_parquet_round_trip_preserves_timezone
tests/test_timestamp_semantics_v03.py::test_run_finished_at_present_and_utc
tests/test_timestamp_semantics_v03.py::test_time_key_aware_input_converted_to_market_time
tests/test_timestamp_semantics_v03.py::test_utc_conversion_across_seasons
tests/test_v060_integrated_e2e.py::test_complete_chain_all_six_cli_steps
tests/test_v060_integrated_e2e.py::test_empty_chain_through_catalog
tests/test_v060_integrated_e2e.py::test_matrix_a_generation_identical_across_roots
tests/test_v060_integrated_e2e.py::test_matrix_b_dataset_identity_cwd_and_location_independent
tests/test_v060_integrated_e2e.py::test_security_symlinked_canonical_dir_fails_closed
tests/test_v060_integrated_e2e.py::test_security_symlinked_dataset_candidate_fails_closed
tests/test_v060_integrated_e2e.py::test_security_symlinked_generation_plan_fails_closed
tests/test_v060_integrated_e2e.py::test_security_symlinked_snapshot_dir_fails_closed
tests/test_v070_artifact_client_catalog.py::test_catalog_client_read_matches_direct_formal_reader
tests/test_v070_artifact_client_catalog.py::test_catalog_method_binding_stays_lightweight_in_fresh_interpreter
tests/test_v070_artifact_client_foundation.py::test_artifact_client_is_exported_in_all
tests/test_v070_artifact_client_foundation.py::test_artifact_client_is_importable_at_top_level
tests/test_v070_artifact_client_foundation.py::test_artifact_client_module_has_no_module_level_imports_besides_future
tests/test_v070_artifact_client_foundation.py::test_constructor_works_in_empty_cwd_without_settings
tests/test_v070_artifact_client_foundation.py::test_market_vault_remains_lazily_importable
tests/test_v070_artifact_client_foundation.py::test_plain_import_stays_lazy_and_loads_nothing_heavy
tests/test_v070_artifact_client_foundation.py::test_reader_imports_are_method_local_only
tests/test_v070_artifact_client_readers.py::test_canonical_client_read_matches_direct_reader
tests/test_v070_artifact_client_readers.py::test_canonical_method_call_boundary_loads_only_reader_chain
tests/test_v070_artifact_client_readers.py::test_catalog_client_read_matches_direct_reader
tests/test_v070_artifact_client_readers.py::test_catalog_method_call_boundary_loads_only_reader_chain
tests/test_v070_artifact_client_readers.py::test_dataset_client_read_matches_direct_reader
tests/test_v070_artifact_client_readers.py::test_dataset_method_call_boundary_loads_only_reader_chain
tests/test_v070_integrated_e2e.py::test_example_execution_against_real_chain
tests/test_v070_integrated_e2e.py::test_fresh_interpreter_import_and_binding_stays_lazy
tests/test_verified_dataset_reader.py::test_build_dir_symlink_rejected
tests/test_verified_dataset_reader.py::test_dst_fall_back_boundary_case
tests/test_verified_dataset_reader.py::test_dst_spring_forward_boundary_case
tests/test_verified_dataset_reader.py::test_feature_specs_junction_rejected_before_descent
tests/test_verified_dataset_reader.py::test_feature_specs_symlink_rejected_before_descent
tests/test_verified_dataset_reader.py::test_junction_entry_rejected
tests/test_verified_dataset_reader.py::test_label_specs_junction_rejected_before_descent
tests/test_verified_dataset_reader.py::test_label_specs_symlink_rejected_before_descent
tests/test_verified_dataset_reader.py::test_local_timezone_change_does_not_affect_result
tests/test_verified_dataset_reader.py::test_model_built_at_normalized_equivalent_representation
tests/test_verified_dataset_reader.py::test_mtime_change_does_not_affect_identity
tests/test_verified_dataset_reader.py::test_nested_ancestor_symlink_rejected
tests/test_verified_dataset_reader.py::test_parent_symlink_rejected
tests/test_verified_dataset_reader.py::test_parquet_content_id_metadata_mismatch
tests/test_verified_dataset_reader.py::test_parquet_corrupt
tests/test_verified_dataset_reader.py::test_parquet_dataset_id_metadata_mismatch
tests/test_verified_dataset_reader.py::test_parquet_dictionary_string_rejected
tests/test_verified_dataset_reader.py::test_parquet_exact_arrow_schema_and_rows
tests/test_verified_dataset_reader.py::test_parquet_feature_null_rejected
tests/test_verified_dataset_reader.py::test_parquet_materializer_version_metadata_mismatch
tests/test_verified_dataset_reader.py::test_parquet_metadata_exact
tests/test_verified_dataset_reader.py::test_parquet_metadata_extra_rejected
tests/test_verified_dataset_reader.py::test_parquet_metadata_missing_rejected
tests/test_verified_dataset_reader.py::test_parquet_nan_rejected
tests/test_verified_dataset_reader.py::test_parquet_negative_infinity_rejected
tests/test_verified_dataset_reader.py::test_parquet_null_contract
tests/test_verified_dataset_reader.py::test_parquet_pandas_metadata_rejected
tests/test_verified_dataset_reader.py::test_parquet_positive_infinity_rejected
tests/test_verified_dataset_reader.py::test_parquet_row_count_mismatch
tests/test_verified_dataset_reader.py::test_parquet_row_order_metadata_mismatch
tests/test_verified_dataset_reader.py::test_parquet_scalar_types_readback
tests/test_verified_dataset_reader.py::test_parquet_schema_id_metadata_mismatch
tests/test_verified_dataset_reader.py::test_parquet_wrong_column_order
tests/test_verified_dataset_reader.py::test_parquet_wrong_dtype
tests/test_verified_dataset_reader.py::test_parquet_wrong_nullability
tests/test_verified_dataset_reader.py::test_rederived_schema_exact
tests/test_verified_dataset_reader.py::test_relocation_passes_and_identity_stable
tests/test_verified_dataset_reader.py::test_schema_field_order_and_types
tests/test_verified_dataset_reader.py::test_second_parquet
tests/test_verified_dataset_reader.py::test_second_pass_manifest_symlink_race_rejected
tests/test_verified_dataset_reader.py::test_success_junction_rejected
tests/test_verified_dataset_reader.py::test_success_symlink_rejected
tests/test_verified_dataset_reader.py::test_symlink_entry_rejected
tests/test_verified_dataset_reader.py::test_symlink_relocation_rejected
```

