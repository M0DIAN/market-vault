"""Frozen version constants and the unified error of the v0.6.0 Sample
Generation CLI contract (PR-4).

This module defines the Sample Generation CLI layer's own contract surface:

- :data:`SAMPLE_GENERATION_CLI_CONTRACT_VERSION` — the version of the
  ``sample-generate`` input/output contract. It describes the CLI only; it
  never enters ``generation_content_id``, ``dataset_id``, the generated
  build-plan bytes, or any artifact;
- :data:`SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION` — the version of the
  deterministic CLI result JSON contract (success and failure outputs of
  ``sample-generate``);
- :class:`SampleGenerationCLIError` — the unified documented error of the
  Sample Generation command layer.

The Sample Generation CLI contract is deliberately independent of the
existing Dataset CLI contract
(:mod:`market_vault.dataset.cli_models`): ``sample-generate`` is not a
Dataset command, never reuses
``DATASET_CLI_CONTRACT_VERSION`` /
``DATASET_CLI_RESULT_SCHEMA_VERSION``, and never changes the existing
build-plan schema. Nothing here reads or writes the filesystem and no
current time is used.
"""

from __future__ import annotations

__all__ = [
    "SAMPLE_GENERATION_CLI_CONTRACT_VERSION",
    "SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION",
    "SampleGenerationCLIError",
]

#: Version of the Sample Generation CLI input/output contract (described in
#: ``docs/contracts/sample_generation.md``). It records the CLI contract
#: only and never enters ``generation_content_id``, ``dataset_id``, the
#: generated build-plan bytes, or any artifact.
SAMPLE_GENERATION_CLI_CONTRACT_VERSION = "market-vault-sample-generation-cli-v1"

#: Version of the deterministic Sample Generation CLI result JSON contract
#: (success and failure outputs of ``sample-generate``).
SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-sample-generation-cli-result-v1"
)


class SampleGenerationCLIError(Exception):
    """Unified documented failure of the Sample Generation command layer.

    Raised for strict generation-plan path violations, relative-path /
    output-parent policy violations, output-plan materialization failures
    (exact-byte idempotency, no-overwrite, write failures), and every
    documented failure of the underlying formal layers
    (:class:`SampleGenerationError`, :class:`SplitValidationError`,
    :class:`DatasetCLIError` from the existing build-plan parser,
    ``OSError``, ``UnicodeError``, ``json.JSONDecodeError`), each converted
    with its ``__cause__`` preserved and never double-wrapped. The command
    layer never uses broad ``except Exception``: real programming errors
    (``RuntimeError``, ``AssertionError``, and friends) are not disguised
    as user input errors and are never converted.
    """
