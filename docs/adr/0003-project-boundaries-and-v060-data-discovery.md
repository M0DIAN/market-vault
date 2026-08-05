# ADR 0003: Separate trusted data production, quant research, and trading execution

- Status: Accepted
- Deciders: MarketVault maintainers
- Date: 2026-08-06
- Related: [ADR 0001](0001-canonical-ml-dataset-boundary.md),
  [ADR 0002](0002-deterministic-dataset-builder-boundary.md),
  [v0.5.1 direction](../v0_5_1_direction.md),
  [v0.6.0 direction](../v0_6_0_direction.md)

## Context

MarketVault has produced trusted, verified, immutable data layers
(Canonical builds, Datasets) and now plans two additional v0.6.0 data
capabilities: the Deterministic Sample Generator and the immutable Dataset
Catalog. The open question is where the overall system boundary sits: what
lives inside MarketVault, what belongs to a future quant research system,
and what belongs to a future trading execution system.

The three categories of systems have different engineering goals:

- **Data systems** emphasize immutability, verification, determinism,
  point-in-time correctness, and identity binding. A wrong or silent data
  mutation can corrupt every downstream artifact, so the data layer must
  fail closed.
- **Research systems** emphasize iteration: models, random seeds,
  experiments, metrics, and predictions. Research code changes quickly and
  must never be able to silently modify a formal Dataset.
- **Trading systems** emphasize real-time behavior, account permissions,
  risk management, order idempotency, and recovery. Trading credentials and
  execution state must never enter a data project.

V0.5.1 sealed the trusted data baseline. V0.6.0 adds Sample Generator and
Dataset Catalog capabilities while keeping every existing identity and
contract unchanged. This ADR fixes the boundaries among the three future
systems so the v0.6.0 contracts can be designed without mixing
responsibilities.

## Decision

Adopt the three-project boundary:

```text
MarketVault
Future Quant Research
Future Trading Execution
```

1. **MarketVault** remains the trusted data production project. It owns
   Canonical, Feature/Label execution, Dataset builds, the Sample Generator,
   and the Dataset Catalog, and it will later provide the Python Client as
   a consumption interface. MarketVault never trains models, never
   backtests, and never executes orders.

2. **Future Quant Research repository** (not yet created) owns experiment
   management, training, evaluation, prediction, and research backtests.
   It consumes trusted Datasets through verified readers or the future
   Python Client and must record `dataset_id` for every experiment.

3. **Future Trading Execution repository** (not yet created) owns signal
   consumption, risk management, paper trading, and order / live execution.
   It consumes research artifacts through versioned contracts only and
   never writes into MarketVault Datasets.

4. **V0.6.0 scope.** V0.6.0 only adds the Sample Generator and the Dataset
   Catalog to MarketVault. It creates no new repository, no research
   functionality, and no trading functionality.

## Consequences

### Positive

- Research code cannot silently modify a formal Dataset; the data project
  stays immutable and verifiable.
- Trading credentials never enter the data project.
- Datasets can be reproduced and verified independently of any model or
  execution system.
- Models and execution systems can upgrade independently of the data
  contracts.
- Data contracts stay stable while research and trading iterate.

### Negative

- Cross-project artifact contracts must be explicit: what a research
  experiment may consume, and what a trading system may consume, must be
  documented.
- Quant Research experiments must record `dataset_id` (and the Catalog
  snapshot identity where relevant) so results are reproducible.
- A Python Client or a stable reader interface is eventually required for
  consumption; it is fixed as a later direction, not part of v0.6.0.
- Live trading signals must have a separate versioned contract between the
  research and trading projects.

### Neutral

- The Sample Generator and Dataset Catalog boundaries remain inside
  MarketVault and are governed by the existing fail-closed, deterministic,
  no-network principles.
- No existing identity algorithm or contract changes.

## Rejected alternatives

1. **Putting training, backtesting, signals, and trading all into
   MarketVault.** Rejected: it would couple fast-iterating research and
   credential-bearing execution to the immutable data layer, allowing
   research bugs to corrupt formal Datasets and execution credentials to
   leak into the data project.
2. **Letting research code read Parquet directly and bypass the verified
   reader.** Rejected: bare reads cannot verify identity, content, or
   `_SUCCESS`; they break the verified-readers-as-trust-boundaries model.
3. **Reusing the legacy ingestion `market_vault.storage.catalog.Catalog`
   for the Dataset Catalog.** Rejected: the legacy Catalog tracks ingestion
   runs, quality results, snapshots, and DuckDB views; the Dataset Catalog
   indexes verified immutable Dataset builds and has different identity,
   verification, and immutability requirements.
4. **Letting the Sample Generator execute model training.** Rejected: the
   generator only produces `PITSampleRequest` sequences and an ordinary
   `market-vault-dataset-build-plan-v1`; training belongs to the future
   Quant Research repository.
5. **Letting the trading project modify MarketVault Datasets.** Rejected:
   Datasets are immutable; trading consumes versioned contracts and must
   never write into the data project.

No actual new repository is created by this ADR.
