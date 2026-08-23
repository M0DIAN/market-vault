# Destructive Operation Governance

## Required Workflow

MarketVault uses a two-PR design gate for operations that can make persistent
user or runtime state unavailable, replaced, quarantined, restored over,
incompatibly migrated, or permanently removed:

```text
design-only PR -> independent review -> merge -> implementation PR
```

**Destructive implementation and first approval of its design contract must
not be merged in the same PR.** The implementation PR must start from a base
commit that already contains its approved contract. A material contract change
also requires a separate design-only PR first.

Prompt text, developer intent, and review discussion are not safety boundaries.
The JSON contract is the semantic boundary,
`scripts/check_destructive_design_gate.py` plus CI is the machine boundary, and
repository permissions remain the authority boundary.

## Covered Operations

The gate covers product operations involving delete, purge, restore, garbage
collection, persistent cleanup, overwrite or replacement, destructive schema
or data migration, truncate/drop, and quarantine lifecycle mutation. It also
covers uncertain production AST surfaces until they receive a bounded
classification.

Temporary-file cleanup and atomic staging publication are not automatically
product-level destructive operations. Existing instances are allowed only by
the machine-readable exemption registry. Every exemption binds an exact source
file, symbol, AST call fingerprint, signal, and occurrence count. Wildcards and
directory-wide exemptions are prohibited, so nearby new logic is not covered.

## Contracts And Checks

Contracts live at:

```text
docs/governance/destructive_operations/<operation_id>.json
```

They describe authority, persistent scope, state transitions, commit point,
crash behavior, rollback and recovery, idempotence, locking, execution-time
revalidation, integrity-bound success evidence, path/reparse safety, stale UI
state, physical atomicity, unsupported cascades, permanent deletion policy, and
required implementation evidence. Planned bindings may name future exact files
and symbols, allowing design approval before source exists.

Run a complete local consistency check with:

```powershell
python scripts/check_destructive_design_gate.py --repo . --mode repository --inventory
```

On pull requests, CI supplies the exact base and head. A new or changed
destructive implementation must resolve to one unchanged approved contract in
the base tree. A HEAD-only contract cannot authorize that implementation. A
contract-only PR may pass without its planned source existing. Parse errors,
unknown schema or enum values, malformed Git evidence, unclassified surfaces,
unused or overbroad exemptions, and ambiguous ownership fail closed.

## Current Registration

`safe_purge_v01.json` bootstraps the already-reviewed Safe Purge behavior
without changing it. `exemptions.json` inventories existing bounded staging,
lock-release, atomic-report, idempotent Catalog-recording, and derived-view
refresh primitives. The checker is static analysis and cannot prove arbitrary
runtime intent, reflection, dynamically generated SQL, native extensions, or
external consumers. Review remains required; uncertainty must produce a new
design contract or a narrowly reviewed exemption rather than an assumption.
