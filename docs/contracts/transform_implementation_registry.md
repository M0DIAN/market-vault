# Transform Implementation Registry Contract

Status: implemented in the v0.5.0 PR-2 dataset layer
(`market_vault.dataset.transform_models` and
`market_vault.dataset.transform_registry`).

This contract defines the explicit immutable **Transform Implementation
Registry**: the frozen registration models, the exact `transform_ref`
lookup key, strict FeatureSpec/LabelSpec compatibility preflight, exact
parameter-schema validation, the versioned deterministic implementation
fingerprint, and its conversion to the existing
[ImplementationPin](derived_dataset_manifest.md) /
`DatasetIdentityInput.implementations` / `dataset_id` identity mechanism.
The boundary decision is in
[ADR 0002](../adr/0002-deterministic-dataset-builder-boundary.md) (decision
3) and [v0_5_0_direction.md](../v0_5_0_direction.md) (section 6); the
Feature/Label spec contract it validates against is
[feature_label_spec_versioning.md](feature_label_spec_versioning.md).

This PR does **not** contain any built-in Feature or Label transform, does
**not** execute any transform, does **not** compute any Feature or Label
value, does **not** assemble PIT rows or `actual_label_end_time`, does
**not** produce `label_status`, does **not** build a Dataset, does **not**
write Dataset Parquet, has **no** Dataset reader or CLI, and performs
**no** network access.

## 1. Status and scope

- **Implemented:** frozen registration models; the immutable exact-key
  registry; strict spec preflight; exact parameter-schema validation;
  versioned deterministic implementation fingerprints;
  `ImplementationPin` generation; `DatasetIdentityInput` integration
  tests; offline contract documentation.
- **Not implemented (future PRs):** built-in Feature transforms (PR-3),
  built-in Label transforms (PR-4), the transform executor, PIT row
  execution, `actual_label_end_time`, label completeness, Dataset
  orchestration/materialization, Dataset Parquet, the verified Dataset
  reader, the Dataset CLI.
- **Version:** the package version remains `0.4.0` (no pyproject.toml,
  dependency, or version change).

## 2. Relationship to ADR 0002

ADR 0002 decision 3 requires: only built-in, registered, versioned
transforms execute; `transform_ref` resolves only against the registry
(never the filesystem or the network); the exact lookup key is the complete
v1 `module.path:function` string; every registered implementation declares
input requirements, output contract, parameter schema, lookback /
lookforward, boundary policy, null/incomplete policy, and a deterministic
implementation fingerprint under a versioned payload contract; and the
registry emits `ImplementationPin(name, version, content_sha256)` entries
into `DatasetIdentityInput.implementations`. This PR implements exactly
that registry contract; execution and computation remain future PRs.

## 3. Public API

Public constants:

- `TRANSFORM_REGISTRY_CONTRACT_VERSION = "market-vault-transform-registry-v1"`
- `TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION =
  "market-vault-transform-implementation-fingerprint-v1"`
- `SPEC_KIND_FEATURE` / `SPEC_KIND_LABEL` (reused from the existing core;
  no second kind vocabulary is introduced)
- `PARAMETER_TYPE_BOOL = "bool"`, `PARAMETER_TYPE_INT64 = "int64"`,
  `PARAMETER_TYPE_FLOAT64 = "float64"`, `PARAMETER_TYPE_STRING = "string"`
  (the canonical scalar names of the existing logical-type set)
- `WINDOW_SOURCE_NONE | FIXED | PARAMETER | LABEL_OBSERVATION_WINDOW |
  LABEL_HORIZON`
- `WINDOW_UNIT_NONE | BARS | MINUTES`
- `WINDOW_BOUNDARY_INCLUSIVE | EXCLUSIVE`
- `BOUNDARY_POLICY_PIT_WINDOW_ONLY | SAME_MARKET_CALENDAR_DATE |
  NO_CROSS_TRADING_DAY`
- `MISSING_POLICY_FAIL | EXCLUDE_SAMPLE | LABEL_INCOMPLETE`

Public types and functions:

| API | Behavior |
| --- | --- |
| `TransformRegistryError` | Unified fail-closed error (subclass of the existing `DatasetError`). |
| `TransformParameterContract` | One typed parameter contract. |
| `TransformWindowRequirement` | One typed lookback / lookforward requirement. |
| `TransformRegistration` | One frozen registration of a module-level implementation. |
| `ResolvedTransform` | Strictly validated result of one resolution: original frozen spec, registration, validated parameters, `ImplementationPin`. |
| `TransformRegistry(registrations)` | Immutable exact-key registry with `resolve_spec`, `resolve_feature_spec`, `resolve_label_spec`. |
| `transform_implementation_fingerprint(registration)` | 64-character lowercase SHA-256 of the versioned fingerprint. |
| `transform_implementation_pin(registration)` | Existing `ImplementationPin(name=transform_ref, version=implementation_version, content_sha256=<fingerprint>)`. |

Internal source-normalization helpers and lower-level constructors that
could bypass validation are not exported. All failures surface as
`TransformRegistryError`; no bare `KeyError`, `TypeError`, `ValueError`, or
`inspect` exception leaks.

## 4. Registration model

`TransformRegistration` is frozen and validates at construction:

- `transform_ref` (exact v1 `module.path:function` key);
- `kind` (FEATURE or LABEL, reusing `SPEC_KIND_FEATURE` / `SPEC_KIND_LABEL`);
- `implementation_version` (safe non-empty text);
- `implementation` (module-level callable, stored but never executed);
- `input_canonical_fields` (non-empty, unique; order is authoritative
  semantics and preserved exactly);
- `supported_canonical_schema_versions` / `supported_source_schema_versions`
  (non-empty, unique, deterministically sorted — order is not semantic);
- `output_arity` (fixed to 1 by the v1 contract: one spec, one output
  `DatasetField`; the output name always comes from `spec.output.name`,
  never from the registration), `output_logical_type` (one of the existing
  `SUPPORTED_LOGICAL_TYPES`), `output_nullable`;
- `parameters` (tuple of `TransformParameterContract`, sorted by name,
  duplicates fail closed);
- `lookback` / `lookforward` (`TransformWindowRequirement`);
- `boundary_policy`, `missing_policy` (fixed constants);
- `display_name` (optional human-readable text; never replaces
  `transform_ref`);
- `implementation_fingerprint` (computed once at construction; the
  registration is then a frozen snapshot).

Duplicates always fail closed (never silently deduplicated); immutable
storage uses tuples, never mutable dicts or lists.

## 5. Exact `transform_ref` key

The lookup key is the complete v1 string `module.path:function`, matching
the FeatureSpec/LabelSpec v1 shape. It must additionally satisfy

```text
transform_ref == implementation.__module__ + ":" + implementation.__name__
```

There is no short-name completion, no alias fallback, no case-insensitive
lookup, no partial-name resolution, and no reinterpretation of short names
such as `simple_return`. `transform_ref` is identity-bearing and never
silently normalized.

## 6. No dynamic import rule

The registry never imports anything. Resolution looks up the exact string
in its own immutable registration set; construction looks up the
implementation's **already-loaded** module in `sys.modules` (a plain dict
lookup, never `importlib`), verifies the module attribute is the function
object, and reads the module's stable source file for the fingerprint.
Forbidden: `importlib` dynamic imports, YAML-path module loading, `eval`,
`exec`, decorator-based global registration, package / entry-point /
filesystem scanning, and network access.

## 7. Parameter schema

`TransformParameterContract(name, value_type, nullable, lower_bound,
upper_bound, allowed_values)` supports the same base scalars as the
existing `SpecParameter`: real `bool`, signed `int64` (strict
`[-2**63, 2**63-1]`), finite `float64`, safe `string`, and explicit `null`
(only when `nullable` is true). `bool` is never `int`; int64 values must be
in range; float values must be finite (NaN / ±Infinity fail); numeric
bounds are inclusive and allowed only on numeric contracts
(`lower_bound <= upper_bound`); `allowed_values` is a non-empty,
deterministically sorted, duplicate-free set of exact-type scalars.

The v1 registry provides **no implicit runtime defaults**: every
behavior-affecting parameter must exist explicitly in the
FeatureSpec/LabelSpec. At resolve time the spec parameter set must match
the registration schema **exactly**: missing parameters fail, unknown
parameters fail, duplicates fail (already rejected by the spec model), and
each value is validated against its contract (type, nullability, bounds,
allowed values). Validated parameters are returned in stable name order;
the frozen spec is never modified.

## 8. Input / output compatibility

At resolve time the registry verifies, fail closed:

1. `transform_ref` exists in the registry exactly;
2. `registration.kind == spec.kind`;
3. `spec.input_canonical_fields` equals the registration's input contract
   exactly, **including order** (input order is authoritative semantics);
4. `spec.output.logical_type` equals the registration's
   `output_logical_type`;
5. `spec.output.nullable` equals the registration's `output_nullable`;
   (output arity is structurally fixed to 1; `spec.output.name ==
   spec.name` is enforced by the existing spec model);
6. every `spec.requirements.canonical_schema_versions` entry is supported
   by the registration — the registration may support more versions and the
   spec is never modified to match;
7. every `spec.requirements.source_schema_versions` entry is supported;
8. the parameter schema passes exactly (section 7);
9. the registration is valid — guaranteed at construction, where every
   registration is fully validated and its fingerprint is a frozen
   snapshot.

Resolution never executes the transform.

## 9. Window requirement

`TransformWindowRequirement(source, unit, value, parameter_name, boundary)`
is typed and version-stable. Sources:

- `NONE` — no requirement; must not carry a value or parameter name;
- `FIXED` — a positive integer in `unit` (BARS or MINUTES);
- `PARAMETER` — the declared **non-nullable int64** parameter named by
  `parameter_name` (must exist in the registration's parameter schema);
- `LABEL_OBSERVATION_WINDOW` / `LABEL_HORIZON` — the LabelSpec's own
  declared observation window / horizon, allowed only on a LABEL
  registration's lookforward; the declared unit must equal the spec's unit
  at preflight.

A `PARAMETER` window size is a positive integer, enforced at both
construction and resolve time:

- at registration construction, the referenced parameter contract must be
  `value_type == int64`, `nullable == false`, must declare a numeric
  `lower_bound >= 1`; an existing `upper_bound` must not be below the
  `lower_bound`; and existing `allowed_values` must all be real positive
  ints;
- at spec resolve, the actual `SpecParameter` value is re-validated: it
  must be a real `int` with `value >= 1` — bool, null, zero, and negative
  values fail closed.

Units are `NONE | BARS | MINUTES`. `TRADING_DAYS` is not part of the v0.5
execution scope and has no unit constant; a TRADING_DAYS label fails closed
(section 11). `boundary` records the inclusive/exclusive semantics of the
window edge bar (`INCLUSIVE` is the documented v1 default; `EXCLUSIVE` must
be declared explicitly). A FEATURE registration's lookforward must be
`NONE`, and no registration's lookback may derive from a Label source.
This layer only records and preflights these requirements; no window is
computed and no PIT row is read.

## 10. Boundary and missing policies

Fixed constants only; no free text.

Boundary policies: `PIT_WINDOW_ONLY`, `SAME_MARKET_CALENDAR_DATE`,
`NO_CROSS_TRADING_DAY`.

Missing/incomplete policies: `FAIL`, `EXCLUDE_SAMPLE`,
`LABEL_INCOMPLETE`. A FEATURE registration must not use
`LABEL_INCOMPLETE`; a LABEL registration may.

## 11. v0.5 Label boundary gates (preflight)

At resolve/preflight time, fail closed as unsupported in the v0.5
execution scope:

- a LabelSpec with `horizon.unit == TRADING_DAYS`;
- a LabelSpec with `cross_trading_day.allow == true` (even with a BARS or
  MINUTES horizon — the v1 opt-in mechanism exists in the spec contract,
  but no execution path implements it in v0.5).

A normal BARS / MINUTES label with the default no-cross-trading-day policy
resolves. This is configuration preflight only; no label window is
assembled and no `label_status` is generated.

## 12. Callable restrictions

The registry accepts only a plain, stable, module-level Python function:

- must be a `types.FunctionType` (bound methods, callable objects, and
  builtins are rejected);
- not a lambda (`__name__ == "<lambda>"` rejected);
- not nested/local (`"<locals>" in __qualname__` rejected);
- no closure cells (`__closure__ is None` required);
- not a generator function;
- not an async function or async generator;
- `transform_ref == __module__ + ":" + __name__` exactly;
- the module must be loaded, the module attribute must be the function
  object, and stable Python source must be readable (a module with no
  `__file__`, a missing file, or unreadable source fails closed).

The callable is **never executed** — not at construction, not at
fingerprint time, not at resolve time. The future executor signature is
defined by PR-3/PR-4, not by this PR.

## 13. Source normalization

The fingerprint hashes the **complete source of the implementation's
module** (not just the function body), so module-local helpers, constants,
and shared calculation code participate. The normalization contract:

1. obtain the module source with `inspect.getsource(module)`;
2. no absolute path, checkout directory, or filename enters the payload;
3. UTF-8 encoding;
4. Unicode NFC normalization;
5. CRLF and CR normalized to LF;
6. leading and trailing blank lines removed;
7. exactly one final LF;
8. NUL and unsafe control characters (C0 except tab/newline, DEL, C1)
   are rejected — fail closed rather than guess;
9. the normalized UTF-8 bytes are SHA-256 hashed.

No per-line trimming is applied: every character of the source content,
including trailing whitespace inside string literals and on ordinary code
lines, is preserved intact. Explicitly excluded from the fingerprint:
absolute paths, checkout directories, filesystem mtimes, file owners,
memory addresses, `repr(function)`, `id(function)`, import order, registry
insertion order, and local line-ending style. Only newline-style, path,
and mtime differences are guaranteed fingerprint-neutral; any other source
character change — including whitespace inside a string literal — may
change the fingerprint (conservatively, trailing whitespace on ordinary
code lines may also change it). Bytecode / `co_code` is never used: it
varies across Python versions and does not fully cover semantic
dependencies.

## 14. Fingerprint payload

`transform_implementation_fingerprint` returns a 64-character lowercase
SHA-256 over the versioned payload built with the existing versioned
identity encoding (`encode_identity`, identity encoding version `v1`). The
payload contains at least:

- `TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION` (the fingerprint version
  is part of the payload);
- `TRANSFORM_REGISTRY_CONTRACT_VERSION`;
- `transform_ref`; `kind`; `implementation_version`; `display_name`;
- the canonical source digest (`source_sha256`);
- the input field contract (count / index / value encoding, order
  preserved);
- the supported canonical and source schema versions (sorted);
- the output contract: `output_arity`, `output_logical_type`,
  `output_nullable`;
- the parameter schema (per-contract name, value type, nullability,
  bounds, allowed values);
- the lookback and lookforward requirements (source, unit, value,
  parameter name, boundary);
- the boundary policy and the missing/incomplete policy.

Arrays are encoded explicitly via count / index / value fields; all values
are scalars supported by the existing serializer; Python's
process-randomized `hash()`, dict insertion order, and local timezones
never participate. The fingerprint is a construction-time snapshot: later
edits of the module source file do not change an already-constructed
registration.

## 15. ImplementationPin mapping

`transform_implementation_pin(registration)` reuses the existing model:

```python
ImplementationPin(
    name=registration.transform_ref,
    version=registration.implementation_version,
    content_sha256=transform_implementation_fingerprint(registration),
)
```

The generated `content_sha256` is always a real 64-character lowercase
SHA-256 (never None). There is no second `ImplementationPin` model and no
reimplementation of the existing identity serializer.

## 16. Immutable Registry

`TransformRegistry(registrations)`:

- is frozen; nothing can be registered, replaced, or removed after
  construction (`replace=True` is not offered, and there is no mutable
  register-after-construction API);
- sorts registrations deterministically by `transform_ref`;
- rejects duplicate `transform_ref` values — even when the two
  registrations are byte-identical, never silently overwriting;
- resolves unknown `transform_ref` values fail closed;
- an **empty registry is allowed** and fails closed on every resolve
  (unknown transform) — documented decision;
- every construction failure — including a non-iterable `registrations`
  argument (`None`, a bare int, a bare object) — surfaces as
  `TransformRegistryError`; no bare `TypeError` leaks;
- has no global decorator registration, no import side-effect
  registration, no package / entry-point / filesystem scanning, and no
  network access; importing the package creates no global registry.

## 17. Resolve / preflight behavior

`registry.resolve_spec(spec)` (and the typed `resolve_feature_spec` /
`resolve_label_spec` wrappers) returns a `ResolvedTransform` carrying:

- the **original frozen spec** (never mutated);
- the immutable `TransformRegistration`;
- the spec's own validated parameters in stable name order (no implicit
  defaults);
- the generated `ImplementationPin`.

`ResolvedTransform` is a strictly validated public result model: its
`__post_init__` verifies (fail closed) that the spec is a `FeatureSpec` or
`LabelSpec`, the registration is a `TransformRegistration` whose `kind`
and `transform_ref` match the spec, the parameters are a tuple of
`SpecParameter` equal to the spec's own parameters exactly, and the pin is
an `ImplementationPin` equal to
`transform_implementation_pin(registration)`. Any inconsistency raises
`TransformRegistryError`; the object stays frozen. The full preflight of
section 8 runs before any result is produced, and resolution never
executes the transform.

## 18. Errors / fail-closed behavior

Every registry, model, preflight, and fingerprint failure raises
`TransformRegistryError`, a subclass of the existing `DatasetError`
(itself a `ValueError`). No bare `KeyError`, `TypeError`, `ValueError`, or
`inspect` exception leaks; error messages are stable and testable. A
warning followed by a "seemingly valid" registration or pin is forbidden.

## 19. DatasetIdentityInput integration

The registry contract version never enters `DatasetIdentityInput` or
`dataset_id` directly. Only the generated `ImplementationPin` entries enter
`DatasetIdentityInput.implementations` (sorted by `(name, version)` by the
existing model). Cross-contract guarantees, all covered by tests:

- same spec + same registration + same source → same pin;
- registry input permutation → same pin;
- implementation version change → pin changes;
- registration metadata change → pin changes;
- real normalized-source content change → pin changes;
- a pin change with all other `DatasetIdentityInput` fields identical →
  `dataset_id` changes.

No existing identity algorithm or version constant is modified, and no
existing `dataset_id` test expectation changes.

## 20. Determinism guarantees

Identical pinned inputs (spec, registration, normalized source) produce
identical fingerprints, pins, and `dataset_id`. The fingerprint never
depends on: absolute paths, checkout directories, mtimes, memory
addresses, `repr`/`id`, import order, registry insertion order, local
newline styles, local timezone, current time, or random values. Only real
semantic changes (source content, registration metadata, implementation
version) change the fingerprint.

## 21. Security boundaries

- No `importlib` dynamic imports; no YAML-path module loading; no `eval`
  or `exec` anywhere in the registry.
- `transform_ref` resolves only against explicit built-in registrations.
- No network, no OpenD, no filesystem scanning, no entry-point scanning.
- The registered callable is never executed by any registry operation.
- All text is safe-text validated (NFC, control characters and reserved
  encoding separators rejected) before it can reach an identity payload.
- Fail closed everywhere; there is no "warn and continue" path.

## 22. PR-3 / PR-4 handoff

This PR deliberately leaves for later PRs:

- **PR-3** — built-in Feature transforms and their executor: the actual
  Feature invocation signature, PIT row consumption under the market /
  archive clocks, lookback semantics, and non-finite output rejection.
- **PR-4** — built-in Label transforms and their executor: real
  `label_status` / `actual_label_end_time`, completeness proofs, and
  no-cross-trading-day enforcement.

The future built-in transforms must live in dedicated transform modules
(not in the identity/core modules) so that unrelated core-module changes
do not cause large-scale fingerprint churn, per the module-source
normalization contract (section 13). The registry contract version and the
fingerprint version are fixed by this PR and must be kept stable.
