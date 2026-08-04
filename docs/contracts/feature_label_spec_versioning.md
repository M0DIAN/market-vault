# Feature / Label Spec Versioning Contract

Status: implemented in the v0.4.0 dataset layer
(`market_vault.dataset.spec_models` and `market_vault.dataset.specs`).

This contract defines the versioned **Feature** and **Label** computation
specifications: frozen typed models, strict YAML parsing, deterministic
semantic content hashing, and conversion to the existing
[SpecPin](derived_dataset_manifest.md) / `DatasetIdentityInput` /
`dataset_id` identity mechanism. Related decisions are in
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md) and
[v0_4_0_direction.md](../v0_4_0_direction.md) (sections 7-10); the sample
assembly contract is
[point_in_time_sample_assembly.md](point_in_time_sample_assembly.md).

This PR does **not** compute any Feature or Label value, build a Dataset,
parse spec files into executable code, import or execute `transform_ref`,
assign splits, purge by actual label end, export Dataset Parquet, create
DuckDB views, add CLI commands, train models, or touch the network.

## 1. What a Feature/Label spec is

A Feature or Label spec is a **versioned computation contract**: a precise,
hashable description of one deterministic transform over canonical rows and
its required inputs. Feature/Label values are generated computations defined
by these specs; they are **not** a new source-of-truth materialized data
layer. Only the Canonical layer is a source of truth, and only the future
Dataset builder executes transforms and materializes Dataset artifacts.

- **FeatureSpec** describes one deterministic, versioned transform of
  canonical rows into a numeric/categorical input: input canonical fields,
  a transform function reference, parameter values, and the canonical /
  source schema versions it requires.
- **LabelSpec** additionally pins the observation window, horizon,
  alignment rule, missing-data policy, and the explicit cross-trading-day
  policy. This PR records and validates the policy only; no Label value is
  computed.

Changing a definition creates a **new spec version**; an existing spec is
never mutated in place.

## 2. Public API

| API | Behavior |
| --- | --- |
| `parse_feature_spec(text) -> FeatureSpec` | Strict YAML parse of one Feature spec document. |
| `parse_label_spec(text) -> LabelSpec` | Strict YAML parse of one Label spec document. |
| `load_feature_spec(path) -> FeatureSpec` | Strict UTF-8 file read + parse; the path never enters identity. |
| `load_label_spec(path) -> LabelSpec` | Strict UTF-8 file read + parse; the path never enters identity. |
| `feature_label_spec_content_id(spec) -> str` | 64-character lowercase SHA-256 of the deterministic semantic content. |
| `feature_label_spec_pin(spec) -> SpecPin` | Existing `SpecPin(kind, name, version, content_sha256)`; kind FEATURE for FeatureSpec, LABEL for LabelSpec. |

Public constants:

- `FEATURE_SPEC_SCHEMA_VERSION = "market-vault-feature-spec-v1"`
- `LABEL_SPEC_SCHEMA_VERSION = "market-vault-label-spec-v1"`
- `FEATURE_LABEL_SPEC_CONTENT_ID_VERSION = "market-vault-feature-label-spec-content-v1"`

All failures — PyYAML errors, Unicode errors, missing-file errors, and model
validation errors — surface as the unified `SpecValidationError`, a subclass
of the existing `DatasetError`. No un-wrapped `yaml.YAMLError`, `KeyError`,
or `TypeError` leaks.

## 3. Feature spec contract (v1)

Top-level YAML fields are exactly:

```yaml
spec_schema_version
kind
name
version
output
inputs
transform
parameters
requirements
```

`kind` must be `FEATURE`; the typed model fixes `kind = FEATURE` and it is
not constructible or forgeable by callers. Field shapes:

```yaml
output:
  name          # must equal the spec name; reuse of the DatasetField model
  logical_type  # one of string | int64 | float64 | bool | date32 | timestamp_us_utc
  nullable      # real bool
inputs:
  canonical_fields: [ ... ]   # non-empty, unique, authoritative order
transform:
  ref           # module.path:function reference; never imported/executed here
parameters: { name: value, ... }  # flat scalar values only
requirements:
  canonical_schema_versions: [ ... ]  # non-empty, unique
  source_schema_versions: [ ... ]     # non-empty, unique
```

Rules:

- `spec_schema_version` must be exactly `FEATURE_SPEC_SCHEMA_VERSION`.
  Unknown, future, or old schema versions **fail closed**; the loader never
  attempts best-effort compatibility.
- `name` matches `^[a-z][a-z0-9_]*$`; `version` matches `^v[1-9][0-9]*$`.
- `output.name` must equal the spec `name`; output reuses the existing
  `DatasetField` validation (NFC names, safe text, supported logical types,
  real bool nullability).
- `input_canonical_fields`: non-empty, unique, NFC-normalized safe text; the
  order is **authoritative semantics** and is preserved exactly into the
  content hash.
- `transform_ref` must match
  `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$`
  (an explicit Python-style `module.path:function` reference). This PR only
  validates the shape; the reference is never imported or executed.
- Parameters sort deterministically by name; duplicate parameter names fail
  (never silently overwritten or deduplicated); bool is never treated as
  int; int values are strictly signed int64 `[-2**63, 2**63-1]`; float NaN /
  ±Infinity fail; `-0.0` and `0.0` are equivalent in identity.

## 4. Label spec contract (v1)

Top-level YAML fields are exactly:

```yaml
spec_schema_version
kind
name
version
output
inputs
transform
parameters
requirements
observation_window
horizon
alignment_rule
missing_data_policy
cross_trading_day
```

`kind` must be `LABEL`; the typed model fixes `kind = LABEL`. Additional
field shapes:

```yaml
observation_window:
  unit          # BARS | MINUTES | TRADING_DAYS (canonical uppercase)
  start_offset  # non-negative real int
  end_offset    # non-negative real int, >= start_offset
horizon:
  unit          # same canonical set
  value         # positive real int
alignment_rule: ALIGN_CLOSE   # canonical uppercase identifier ^[A-Z][A-Z0-9_]*$
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: true | false         # real bool
  boundary_rule: ... | null
```

Rules:

- `spec_schema_version` must be exactly `LABEL_SPEC_SCHEMA_VERSION`; name /
  version / output / inputs / transform rules are identical to Feature.
- `observation_window.unit` must equal `horizon.unit`; bool is rejected for
  offsets and the horizon value; a zero-length window (start == end) is
  allowed.
- `alignment_rule` must be a canonical uppercase safe identifier.
- v1 `missing_data_policy` accepts **only `INCOMPLETE`**. Fill,
  forward-fill, interpolate, zero-fill, and any other synthetic-fill policy
  are not supported; an incomplete horizon is recorded, never filled.
- `cross_trading_day.allow == false` (the default) requires a null
  `boundary_rule` and means the label must not span a
  `market_calendar_date` boundary. `allow == true` requires a non-empty safe
  `boundary_rule` (an explicit opt-in with an explicit boundary rule; no
  hidden defaults or free inference). A `TRADING_DAYS` horizon **requires**
  the explicit `allow: true` opt-in. This PR records the policy only; no
  cross-day Label assembly happens.

## 5. Strict YAML contract

The parser uses the existing PyYAML dependency (no new dependencies) with
the SafeLoader constructor family and is fail-closed:

- duplicate mapping keys are rejected, including nested mappings and flow
  style;
- anchors and aliases are rejected (even unused anchors);
- the YAML merge key `<<` is rejected;
- custom tags (`!custom`) and Python tags (`!!python/...`) are rejected;
  only plain YAML 1.1 scalars and collections are accepted — timestamps,
  binary blobs, and sexagesimal scalars are not;
- multi-document YAML streams are rejected; exactly one document per file;
- the root must be a mapping;
- unknown fields fail at every level — typo'd fields are never silently
  ignored;
- missing required fields fail at every level;
- a UTF-8 BOM is rejected (file loaders read UTF-8 strictly; invalid UTF-8
  bytes fail);
- file paths never enter the spec identity.

Not supported: environment-variable interpolation, YAML
`include`/`import`, executable YAML tags, implicit filesystem resolution,
and network access. `transform_ref` is a reference only.

Note on scalar resolution: PyYAML implements YAML 1.1, so unquoted
`on`/`off`/`yes`/`no` resolve to booleans and strings that look like numbers
resolve to numbers. Quote string values (`"10.9"`) when a string is
intended. Values are validated strictly against the v1 scalar set; a YAML
date (e.g. `2026-01-01`) is rejected as a parameter value.

## 6. Deterministic semantic content identity

`feature_label_spec_content_id` returns a 64-character lowercase SHA-256
over the spec's **semantic content**, built by expanding the typed model
into a flat mapping of scalar values and passing it to the existing
versioned identity encoding (`market_vault.dataset.encoding.encode_identity`,
identity encoding version `v1`). The content-ID version
(`FEATURE_LABEL_SPEC_CONTENT_ID_VERSION`), the spec kind, and the spec
schema version are part of the payload. No new or unversioned hashing scheme
is introduced, and `yaml.dump()` output is never hashed directly.

Arrays are encoded explicitly via `count` / `index` / `value` fields (for
example `input_count`, `input_0000`, `input_0001`, …; `parameter_count`,
`parameter_0000_name`, `parameter_0000_value`, …), never via ambiguous
string joins.

### Semantic hash versus YAML byte hash

The semantic hash describes the **meaning** of the spec, not its physical
text. The following differences never change the ID:

- YAML key order and mapping order (parameters are sorted by name;
  requirements versions are sorted);
- YAML comments, blank lines, and trailing whitespace;
- LF vs CRLF newlines and file encodings of the same text;
- `requirements` list input order (order is not semantic);
- file path and load method;
- NFC-equivalent Unicode text;
- `-0.0` vs `0.0`.

The following changes always change the ID: kind; schema version; name;
spec version; output field name, logical type, or nullability; any input
field's content or the authoritative input order; `transform_ref`; any
parameter name, type, or value; any required version; the Label observation
window (unit or offsets); the horizon (unit or value); the alignment rule;
the missing-data policy; and the cross-trading-day policy or boundary rule.

A definition change therefore always changes the content hash and should
always be paired with a **new spec version**; a new spec version with
identical semantics still hashes identically, which is by design.

## 7. Conversion to the existing SpecPin and dataset identity

`feature_label_spec_pin(spec)` reuses the existing

```python
SpecPin(kind=..., name=..., version=..., content_sha256=feature_label_spec_content_id(spec))
```

with kind FEATURE for `FeatureSpec` and LABEL for `LabelSpec`. There is no
second pin model; `SpecPin` fields, the `DatasetManifest` format, and the
`dataset_id` algorithm are unchanged. Pins produced this way enter
`DatasetIdentityInput.feature_specs` / `label_specs` directly, so:

- identical spec semantics produce identical pins and identical
  `dataset_id`;
- any semantic change produces a different pin and a different
  `dataset_id`;
- two pins with the same `(kind, name, version)` fail closed under the
  existing duplicate-spec contract of the identity core;
- the **ImplementationPin** stays a separate, future binding provided by
  the Dataset builder: `transform_ref` is a reference to an implementation
  that this layer never imports, executes, or hashes, and the spec parser
  never fabricates an `ImplementationPin` or a code hash.

## 8. Cross-trading-day default policy

The default policy **forbids** label windows that span a
`market_calendar_date` boundary (for example deriving a label from bars of
trade date D+1 when the feature window belongs to trade date D). Crossing is
allowed only when the label spec explicitly opts in with
`cross_trading_day.allow: true` **and** declares a non-empty boundary rule.
A `TRADING_DAYS` horizon requires the opt-in. The policy is recorded in the
label spec content hash; this PR does not assemble any label window.

## 9. Missing-data behavior

Canonical market bars contain only observed bars: no synthetic OHLCV rows
are ever generated and missing bars are never interpolated. An incomplete
label horizon produces a sample with declared `label_status: INCOMPLETE`
(section 9 of the direction document); v1 specs record
`missing_data_policy: INCOMPLETE` only. Fill, forward-fill, interpolate,
zero-fill, and synthetic OHLCV are explicitly not supported.

## 10. Schema version gate and upgrades

The schema loader accepts exactly the current versions
(`market-vault-feature-spec-v1`, `market-vault-label-spec-v1`). Unknown,
future, or old versions **fail closed** — no partial or best-effort
interpretation. When a spec schema changes, the schema version constant
changes, the semantic content ID changes (the schema version is part of the
identity), and spec documents carrying the old version stop loading until
they are migrated. The identity encoding version
(`FEATURE_LABEL_SPEC_CONTENT_ID_VERSION`) gates the hash scheme itself; any
change there invalidates every previously published content ID.

## 11. Complete YAML examples

Feature `features/close_return_v1.spec.yaml`:

```yaml
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: close_return
version: v1
output:
  name: close_return
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.features.transforms:close_return
parameters:
  lookback: 5
  use_log: false
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
```

Label `labels/next_day_ret_v1.spec.yaml` (TRADING_DAYS horizon with the
explicit cross-trading-day opt-in):

```yaml
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: next_day_ret
version: v1
output:
  name: next_day_ret
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.labels.transforms:next_day_ret
parameters:
  multiplier: 1
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
observation_window:
  unit: TRADING_DAYS
  start_offset: 0
  end_offset: 1
horizon:
  unit: TRADING_DAYS
  value: 1
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: true
  boundary_rule: END_OF_TRADING_DAY
```

## 12. Explicit non-goals

This contract and PR do not implement: Feature computation; Label
computation; rolling/EMA/RSI/MACD indicators; sample-window generation; PIT
assembly behavior; actual cross-day Label assembly; DatasetManifest build
orchestration; Dataset Parquet writing; the Dataset CLI; chronological
splits; actual-label-end purging; the leakage regression suite; Raw/Curated/
Canonical schemas; the Canonical reader/builder; DuckDB views; OpenD or any
network call; ML dependencies; package version or `requires-python`
changes; CI workflow changes; and no existing test is deleted or weakened.
