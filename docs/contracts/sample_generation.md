# Sample Generation Boundary Contract

Status: planned contract boundary; not implemented in v0.5.1
Target release: v0.6.0

This document fixes the high-level contract boundary for the deterministic
Sample Generator planned for v0.6.0. It is a boundary contract only: no
Sample Generator production code exists, and this document does not invent
the final JSON schema fields. The precise schema, frozen models,
normalization, and content identity are defined by the v0.6.0 Sample
Generation contract PR (PR-2).

## 1. Inputs

The generator requires explicit, high-level inputs:

- an explicit verified Canonical build directory (read through
  `load_verified_canonical_build`);
- an explicit scope;
- an explicit generation rule (window / stride rules);
- an explicit Feature/Label spec path;
- an explicit split spec;
- an explicit `dataset_as_of`;
- an explicit `output_root`;
- an explicit `built_at`;
- an explicit output path.

Every input is explicit; there is no current time input. The generator
never scans for `latest`, never auto-discovers Canonical, never reads the
current time, and never accesses the network, OpenD, or settings.

## 2. Output

The output is an ordinary `market-vault-dataset-build-plan-v1` document:

- `requests` are filled deterministically by the generator;
- all other formal fields keep the current build-plan contract
  ([dataset_cli.md](dataset_cli.md));
- the output can be parsed directly by the existing `dataset-build`
  command (`market-vault dataset-build --plan <PATH>`);
- no hidden side input is introduced;
- the output build-plan itself never enters Dataset identity.

## 3. Determinism

- input order is normalized;
- requests are sorted by a stable key;
- duplicate requests fail or are rejected deterministically per the
  contract;
- timestamps use UTC microseconds;
- the generator never reads the current time;
- no randomness is used;
- no network is used;
- identical inputs produce byte-identical output.

## 4. Trust boundary

- Canonical is consumed only through the formal verified reader
  (`load_verified_canonical_build`);
- every generated request is constructed as a formal `PITSampleRequest`
  and passes its validation;
- the generator never copies PIT validation logic;
- the generator never computes Feature or Label values;
- the generator never claims a sample is necessarily COMPLETE;
- the downstream formal Dataset Builder remains the final execution and
  verification boundary.

## 5. Unsupported

The v0.6.0 Sample Generator does not support:

- adjusted-price PIT (`adjustment = NONE` only);
- cross-trading-day Labels;
- `TRADING_DAYS` label horizons;
- arbitrary user transforms;
- automatic `latest` selection;
- automatic Canonical discovery;
- model training;
- backtesting;
- signals.

## 6. Relationship to the future Catalog

The generator produces build plans that, when executed, produce immutable
Datasets; those Datasets are what the future Dataset Catalog indexes. The
generator itself never reads or writes a Catalog.
