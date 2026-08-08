# MarketVault v0.6.1 CLI Usability Audit

Baseline: `6bb9a9500fae53511ff964f47e5ccea20f3d91f7`

Package: 0.6.0

## Audited commands

The exact 8-command formal set:

```text
dataset-build
dataset-verify
dataset-inspect
sample-generate
dataset-catalog-build
dataset-catalog-verify
dataset-catalog-list
dataset-catalog-show
```

There is no `dataset-catalog-query` command; the query surface is fixed as
the read-only list filters of `dataset-catalog-list`.

## Findings

1. **stdout/stderr/exit behavior was already consistent.** All 8 formal
   commands already use: success -> stdout only, exit 0; documented failure
   -> stderr only, exit 1; argparse usage error -> stderr, exit 2. No
   output-helper consolidation was required; `_write_stdout` and
   `_write_failure` and the result payload builders were not modified.
2. **The top-level `--settings` option lacked explanatory help.** It now
   states that it is used by settings-backed commands and that Dataset,
   Sample Generation, and Dataset Catalog commands ignore it. Option name,
   default, and positioning are unchanged.
3. **Dataset / Sample Generation / Catalog path terminology had minor
   wording drift.** "final Dataset directory" / "final snapshot directory"
   / "snapshot build instant" were normalized to "final Dataset build
   directory" / "final Dataset Catalog snapshot directory" / "Dataset
   Catalog snapshot build instant"; the CLI error path labels "snapshot
   dir" and "candidate build dir" became "snapshot directory" and
   "candidate build directory" in user-facing error text.
4. **Catalog argparse diagnostics exposed internal underscore field
   names.** `built_at`, `trade_date`, and `dataset_id` were switched to the
   actual option spellings `--built-at`, `--trade-date`, and `--dataset-id`
   in user-facing `ArgumentTypeError` messages. Type functions, accepted /
   rejected values, and the exit code 2 boundary are unchanged.
5. **The Dataset example docs had one stale v0.5 wording**
   ("unsupported in v0.5"), now version-neutral ("unsupported by the
   current Dataset contract"), plus consistent "final Dataset build
   directory" terminology and an explicit note that Dataset commands
   ignore `--settings` and remain fully offline.
6. **No formal behavior change was required.** This is wording-only.

## Explicit unchanged matrix

| Aspect | Status |
|---|---|
| command names | unchanged |
| business arguments | unchanged |
| required flags | unchanged |
| defaults | unchanged |
| exit codes | unchanged |
| JSON schemas | unchanged |
| CLI contract versions | unchanged |
| identities | unchanged |
| artifact formats | unchanged |
| read/write behavior | unchanged |
| settings/network behavior | unchanged |

## Before/after wording table

| Location | Before | After |
|---|---|---|
| top-level `--settings` | (no help text) | Settings file for settings-backed commands; Dataset, Sample Generation, and Dataset Catalog commands ignore it |
| `dataset-build --plan` | Path to the versioned Dataset build-plan JSON (all build inputs are declared in the plan; no other option is accepted) | Path to the versioned Dataset build-plan JSON; all Dataset build inputs are declared in the plan |
| `dataset-verify` / `dataset-inspect --build-dir` | Explicit final Dataset directory | Explicit final Dataset build directory |
| `dataset-inspect --offset` | Row offset (default 0; rows are sliced, never reordered) | Zero-based row offset (default 0; rows are sliced, never reordered) |
| `sample-generate --plan` | Path to the versioned Sample Generation plan JSON (all generation inputs are declared in the plan; no other option is accepted) | Path to the versioned Sample Generation plan JSON; all generation inputs are declared in the plan |
| `dataset-catalog-build` (summary) | Build and materialize one immutable Dataset Catalog snapshot | Build one immutable Dataset Catalog snapshot from explicit Dataset candidates |
| `dataset-catalog-build --dataset-root` | Explicit bounded discovery root whose direct 64-hex children are candidates (exactly one candidate mode) | Explicit bounded Dataset discovery root; only direct 64-hex child directories are candidates |
| `dataset-catalog-build --candidate-build-dir` | One explicit Dataset build directory candidate; repeatable (exactly one candidate mode, at least one entry) | Explicit final Dataset build directory candidate; repeatable and mutually exclusive with --dataset-root |
| `dataset-catalog-build --output-root` | Explicit parent directory of the committed snapshot | Explicit parent directory for the committed Dataset Catalog snapshot |
| `dataset-catalog-build --built-at` | Explicit timezone-aware snapshot build instant (never the current time) | Explicit timezone-aware Dataset Catalog snapshot build instant; current time is never used |
| `--snapshot-dir` (all three commands) | Explicit final snapshot directory | Explicit final Dataset Catalog snapshot directory |
| `dataset-catalog-list` (summary) | List verified Catalog snapshot entries with read-only in-memory filters and pagination | List entries from one verified Dataset Catalog snapshot with read-only filters and pagination |
| `--status` | Exact status filter (COMPLETE or EMPTY) | Exact Dataset status filter (COMPLETE or EMPTY) |
| `--dataset-kind` | Exact dataset_kind filter | Exact Dataset kind filter |
| `--symbol` | Membership filter: the symbol must be in scope.symbols | Membership filter: symbol must be present in Dataset scope.symbols |
| `--trade-date` | Membership filter: the date must be in scope.trade_dates | Membership filter: date must be present in Dataset scope.trade_dates |
| `--interval` | Exact scope.interval filter | Exact Dataset scope.interval filter |
| `--adjustment` | Exact scope.adjustment filter | Exact Dataset scope.adjustment filter |
| `--requested-session` | Exact scope.requested_session filter (never matches a null stored session) | Exact Dataset scope.requested_session filter; a stored null never matches |
| `--offset` (catalog list) | Entry offset (default 0; entries are sliced, never reordered) | Zero-based entry offset (default 0; entries are sliced, never reordered) |
| `dataset-catalog-show` (summary) | Show one verified Catalog snapshot entry by exact dataset_id | Show one entry from one verified Dataset Catalog snapshot by exact Dataset ID |
| `--built-at` argparse error | built_at must be timezone-aware; naive datetimes are rejected | --built-at must be timezone-aware; naive datetimes are rejected |
| `--trade-date` argparse error | trade_date must be a valid calendar date, got '...' | --trade-date must be a valid calendar date, got '...' |
| `--dataset-id` argparse error | dataset_id must be a 64-character lowercase SHA-256 hex string | --dataset-id must be a 64-character lowercase SHA-256 hexadecimal string |
| catalog show missing id | dataset_id not found in the verified Catalog snapshot: ... | --dataset-id was not found in the verified Dataset Catalog snapshot: ... |
| CLI error path label | snapshot dir / candidate build dir | snapshot directory / candidate build directory |
| example docs | unsupported in v0.5 | unsupported by the current Dataset contract |

No feature was added by this PR; this is a wording-only usability audit
and polish of the fixed v0.6.1 PR-2 scope.
