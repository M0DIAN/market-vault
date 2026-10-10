# Intraday execution scenarios (Q10)

Q10 evaluates a finite, explicitly ordered set of execution policies over one
[Q7 development comparison](intraday_development_research.md). Data, Features,
strategies, training folds and evaluated DEV dates are common. Entry delay,
stop-new time, flatten time, maximum hold and explicit costs may vary. No TEST
candidate search or automatic winner selection is introduced.

## Plan and defaults

The plan contains exactly these fields:

| Field | Content |
| --- | --- |
| `plan_schema_version` | `market-vault-intraday-execution-scenarios-plan-v1` |
| `comparison_plan` | A complete ordinary Q7 comparison plan; diagnostics cannot be nested |
| `execution_scenarios` | A nonempty ordered list of `{name, execution}` objects |

Every name is unique, nonempty and trimmed. Every `execution` object declares
all six Q6 fields: `commission_bps`, `slippage_bps`, `entry_delay_minutes`,
`stop_new_minutes`, `flatten_minutes`, and `max_hold_bars`. Policies must be
unique after normalization. The number of scenarios times the number of
strategies is at most **64**, checked before source access. Benchmarks do not
count as strategy candidates. There is no implicit extra base scenario.

The embedded comparison's execution policy supplies the ordinary Q7 grammar;
only policies in `execution_scenarios` are evaluated. Thus an unused base
window does not invalidate otherwise valid actual scenarios. The desktop
starts a scenario draft from current settings, requires explicitly entered
costs, and embeds the first actual policy as the comparison's policy. Costs
entered in the scenario dialog suffice even if the common form's cost fields
are blank. No market cost assumption is supplied silently.

All six parameters retain [Q6 execution semantics](intraday_execution_v2.md),
including the scheduled bar grid and rounded forced-flat open. The first
actual child prepares the common Q5 context. Every actual policy's complete
DEV session geometry is then checked **before any fit**. A later invalid
scenario invalidates the action; a partial collection is not returned.

Q5 is verified once per action. Equal fold/alpha fits share one private cache
within that action, with no persistent validation or fitted-model cache.
Each scenario's complete raw Q7 report equals a standalone Q7 run with its
corresponding explicit plan. The benchmark uses that scenario's own windows
and costs; its maximum hold remains the full session grid, independently of
the candidate's maximum hold.

[Q24](intraday_development_research.md) adds
`market-vault-intraday-execution-scenarios-plan-v2` for V2 comparisons, including
quadratic strategies. Wrapper and embedded comparison versions must agree.
Representation joins fold and alpha in the fit-cache key, so linear and
quadratic models cannot collide. The V2 collection and result use
`market-vault-intraday-execution-scenarios-v2` and
`market-vault-intraday-execution-scenarios-result-v2`; each child is an ordinary
`market-vault-intraday-experiment-v2`. Save/Open, exact child export, continuation
and complete collection Replay support both versions. V1 identities and
account rules are unchanged. V2 child Freeze/TEST remains unavailable until
Q26; exporting a child does not change its version or eligibility.

## Complete collection and ordinary child experiments

The additive `market-vault-intraday-execution-scenarios-v1` artifact uses the
existing immutable `StrategyExperiment` writer and ten root fields. Its mode
is `INTRADAY_EXECUTION_SCENARIOS`. Each ordered report row contains
`scenario_index`, `name`, and `experiment`: a complete ordinary Q7 snapshot.
The report binds all children, the normalized plan, data ID, evaluation count
and `scenarios_id`. Existing Q7/Q8 artifact formats are unchanged.

Offline Open validates every child and their shared context, corresponding
predictions, models, prediction errors, prices and session clocks. Complete
ordered ledger price/row-version/slot/phase/timestamp projections must agree
within each child and across scenarios; matching price IDs alone do not suffice.
Policy-dependent actions, account values and trades are not part of this common
raw-price projection. Recursive
collections, diagnostics, frozen selections and TEST records cannot be child
experiments. Names, indices, policies, strategy order and algorithm versions
must match the declared scenarios. These structural checks do not prove that
the recorded computation was actually executed.

Replay first checks algorithm versions, then verifies Q5 once and reproduces
**every child report**, including unselected scenarios and hidden ledger rows.
Recorded child names, notes and environment metadata are retained when
reconstructing identities; environment strings are diagnostic information,
not a numerical replay gate. An explicit relocated Q5 file must have the same
data ID. Source-experiment and Dataset-directory overrides are inapplicable.

Save writes the entire last completed immutable collection. Export extracts
one exact ordinary Q7 child, retaining its original ID and metadata. Both
operations create a new named file or reuse identical bytes through the
existing writer; differing content is never overwritten.

## CLI

Build the plan by wrapping an ordinary Q7 plan and declaring each complete
policy. Paths inside the comparison plan resolve relative to the plan file.

```console
market-vault research-intraday-scenarios --plan /absolute/scenarios-plan.json --experiment /absolute/scenarios.json --name "Execution sensitivity"
market-vault research-experiment-open --experiment /absolute/scenarios.json
market-vault research-experiment-replay --experiment /absolute/scenarios.json
market-vault research-experiment-replay --experiment /absolute/scenarios.json --intraday-data-file /relocated/intraday.json
market-vault research-intraday-export-scenario --experiment /absolute/scenarios.json --expected-experiment-id COLLECTION_SHA256 --scenario-index 1 --expected-child-experiment-id CHILD_SHA256 --output /absolute/selected-development.json
```

Replace `COLLECTION_SHA256` and `CHILD_SHA256` with the exact IDs shown by Open;
the child ID is at `report.scenarios[1].experiment.experiment_id` in this
example. Export requires both identities and the index. A mismatched identity
or out-of-range index fails without writing the destination. Export performs
no Q5 access, fit or execution.

The new commands return `market-vault-intraday-execution-scenarios-cli-result-v1`.
Run returns the complete `collection`; saved-file metadata is under
`experiment`. Common Open/Replay retains the existing intraday V3 envelope.
Semantic failures return structured stderr JSON and exit 1; argparse errors
return exit 2. `--name`/`--notes` on Run requires `--experiment`.

## Desktop and Freeze / TEST handoff

In **Quant Research → Intraday → Development research**, open the execution
scenarios dialog to edit named, complete policies. The overview retains input
order and displays every scenario/candidate and all six policy fields. Its
neutral return change compares the same candidate with the **first entered
scenario**, displayed in percentage points. It does not rank results. This
derived scenario difference never
changes Q7's `return_change_from_first_cost`, which is zero in each ordinary
single-policy child.

Select a scenario and candidate to inspect its own benchmark, predictions,
models, full ledger and [Q9 performance](intraday_performance.md). Save and
Replay act on all scenarios; export acts on the selected child. Language and
view changes preserve saved results and drafts. A failed operation preserves
the last completed result, while a failed replay updates its proof status.

Saving a collection does **not** make the current child a saved Q7 file. Export
that child before using [Freeze / TEST](intraday_final_test.md). Switching to
an unexported scenario removes Freeze availability; the exported path for a
different child is never reused. Q8 receives an ordinary saved Q7 experiment
and keeps its existing explicit candidate selection and independent TEST
account. The collection itself is not a Q8 source.
