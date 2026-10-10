# Complete intraday plans and candidate continuation (Q14)

Q14 saves and loads complete valid research plans and turns one explicitly
selected saved DEV candidate into a single-candidate comparison plan. These
operations read configuration and named files only. They do not load Q5 or
Canonical data, fit, execute, select a winner, freeze a candidate or change
the evidence attached to an existing result.

## Three existing plan grammars

Plan files contain the existing plan object directly, without an experiment
schema or an additional envelope:

| Plan | Existing `plan_schema_version` | Configuration retained |
| --- | --- | --- |
| Comparison | `market-vault-intraday-research-plan-v1` | Common context, ordered strategies and full execution policy |
| Diagnostics | `market-vault-intraday-diagnostics-plan-v1` | Complete comparison plan, selected strategy, ordered axes and costs |
| Execution scenarios | `market-vault-intraday-execution-scenarios-plan-v1` | Complete comparison plan and ordered, named full policies |

[Q24](intraday_development_research.md) adds explicit `-v2` variants of all
three plan versions for ordinary intraday `QUADRATIC_RIDGE` strategies. A V2
diagnostics/scenario wrapper must contain a V2 comparison; a V1 wrapper keeps
the V1 grammar. Save/Load preserves the declared version. Continue preserves
the source comparison's version, selected strategy (including quadratic alpha
and threshold) and exact selected execution cost/policy. Existing V1 files are
not converted.

Only complete plans accepted by these existing normalizers can be saved.
Unfinished editor text, a result envelope, TEST and frozen-selection plans are
not supported plan files. Existing field requirements, strategy grammar and
the 64-evaluation bounds remain in force. Validation does not require the data
file to exist or the currently opened desktop data to match.

The common `data_id`, ordered `feature_fields`, split dates and walk-forward
settings are retained. Strategy and Composite-condition order, full-precision
parameters, diagnostics axis/value/cost order and scenario name/policy order
are retained. Execution policies contain commission, slippage, entry delay,
stop-new minutes, flatten minutes and maximum hold bars.

A complete loaded scenarios plan retains its own
`comparison_plan.execution`, even when that policy differs from its first
scenario. A loaded diagnostics plan likewise retains its common execution
policy and separate `cost_scenarios`. The first scenario or cost row does not
replace a valid common policy. A new scenario form whose unused common cost
fields are blank may materialize the first explicit scenario policy only after
all other original fields validate. Nonempty invalid costs or windows and
invalidated bound policies fail; that fallback does not apply to a complete
loaded plan.

## Locator and file behavior

An already normalized host or Windows absolute `intraday_data_path` is kept
as recorded text. Save, Load and Continue do not reinterpret it relative to
the current working directory, the output folder or the currently opened Q5
file. This permits offline sharing of, for example,
`C:\archive\intraday.json` on another operating system.

An explicitly loaded plan may contain a relative data locator. It is made
absolute once against that input plan file's parent, using the existing path
rules. Dot components, environment expansion and inferred source locations
are not added. After loading, saving the normalized plan elsewhere keeps that
same absolute locator. In-memory serialization requires an absolute locator;
the Save destination never supplies a missing input base.

Canonical bytes use UTF-8 without a BOM, sorted object keys, compact
separators, finite JSON numbers and one trailing newline. Loading accepts
valid noncanonical JSON formatting, but rejects duplicate keys, nonfinite
values and malformed grammar. The writer accepts only validated canonical
normalized bytes, so a pending Save has one exact content identity.

The destination parent must already be a regular directory. Plan files and
their parent chain must not be links. The writer uses exclusive creation
(`xb`), flush/fsync and byte-for-byte readback. An existing byte-identical file
is reused; different existing content is an error, including differently
formatted JSON with the same meaning. No file is overwritten, replaced or
deleted, and no parent directory is created implicitly. Invalid captured
content is rejected before creating a file. A write/readback failure is
reported as a failure; a later attempt can reuse an existing file only if its
actual bytes equal the captured content.

## Continue from an explicit saved candidate

Continue accepts a named ordinary saved Q7 DEV comparison or diagnostics
experiment. It reads that immutable file once, validates zero-based cost and
candidate indices, and extracts the actual selected result. Both indices
default to **0** and must be real nonnegative integers; booleans are rejected.

The new ordinary comparison plan keeps the original common data locator and
context, uses the selected expanded candidate's actual strategy fields, and
uses the selected group's complete execution policy. It contains exactly one
strategy. Diagnostics axes and cost grids are not copied into this new
comparison plan. This is a starting point for explicit editing, not a choice
of optimal parameters or a new computation.

The desktop always supplies the experiment ID and candidate ID captured from
the selected saved result. Each is checked against the file read by the
operation; a changed source or selected candidate fails. API and CLI callers
may omit either guard. Every supplied guard is strictly validated and checked;
without guards, the explicitly named file is the current input. There is no
second file read to discover IDs on the user's behalf.

TEST, frozen selections and whole Q10 collections are rejected. An ordinary
Q7 child explicitly exported from Q10 is supported. Supported historical
recorded configuration can be continued without imposing Freeze's current
algorithm-version gate. This does not change Open, Replay or execution proof.

```console
market-vault research-intraday-plan-from-candidate --experiment /absolute/development.json --output /absolute/continued-plan.json
market-vault research-intraday-plan-from-candidate --experiment /absolute/diagnostics.json --cost-index 1 --candidate-index 3 --output /absolute/selected-plan.json
```

Optional `--expected-experiment-id` and `--expected-candidate-id` add explicit
identity guards. The CLI returns `market-vault-intraday-plan-cli-result-v1`
with the plan, selection indices and written-file metadata. A new file or
byte-identical reuse returns exit 0. Invalid input, identity mismatch,
unsupported mode, out-of-range selection or a destination conflict returns a
FAILED JSON envelope on stderr and exit 1. Noninteger argparse inputs return
exit 2. Use the installed `market-vault` console entry to inspect process exit
codes; settings and OpenD initialization are unnecessary.
Both success and failure envelopes use ASCII JSON escapes so Unicode names
and paths remain readable by JSON consumers on legacy console encodings.
Decoding restores the original text; canonical plan files remain UTF-8.

## Desktop draft and Run behavior

**Save plan** is separate from **Save experiment**. Comparison/settings,
diagnostics and execution-scenarios editors each have an explicit Save plan
entry. The relevant editor commits its current inputs before validation and
captures canonical bytes before opening the file dialog. Accepting the dialog
supplies only the destination path; later edits cannot change that capture.
Save experiment continues to save the last completed immutable result.

**Load plan** changes the editable draft only. **Continue selected candidate**
creates a draft from the explicitly selected saved candidate. Neither action
runs research or changes the current result, its identity, page or proof.
Once a draft is bound by Load or Continue, changing results, opening another
experiment, changing Q5, switching scenario, changing language or reopening
an editor preserves that draft. Only explicit Load or Continue replaces its
plan binding; normal field editing still edits it. Without a bound draft,
the original Open behavior can restore result settings into the forms.

Run validates the complete draft and additionally requires matching currently
opened Q5 identity and available ordered Features. The retained locator must
be an absolute path understood by the host. The public research action still
loads and verifies the plan's own locator; a currently opened same-ID file at
another path is not silently substituted. An unavailable original locator,
foreign-host path or mismatching current data causes an explicit failure and
preserves the draft and previous result. Save and Load remain available for a
valid plan independently of these Run requirements.

## API and task-package scope

`research.intraday_plan` exposes `serialize_intraday_plan`,
`parse_intraday_plan_bytes`, `load_intraday_plan`, `write_intraday_plan` and
`extract_intraday_candidate_plan`. The writer returns `path`,
`plan_schema_version`, `content_sha256` and `created_new_file`. The content hash
identifies file bytes; it is not a new experiment ID or proof field.

| Order | Capability | Boundary |
| --- | --- | --- |
| Q12 | [Risk, distributions, drawdowns and DEV folds](intraday_risk_diagnostics.md) | Derivation from saved records with local availability |
| Q13 | [Saved parameter grid and numeric neighbors](intraday_parameter_grid.md) | Existing candidates and complete recorded comparison basis |
| Q14 | Complete plans and explicit candidate continuation | Configuration reuse followed by a separately requested Run |

The sequence moves from understanding saved results, to describing nearby
recorded parameters, to continuing an explicit choice. It adds no optimizer,
feature-subset study, automatic candidate selection or execution semantics.
Existing Q7/Q8/Q10 artifacts and identities, Q11/Q12/Q13 reports, and the
application/package version **0.9.0** remain unchanged.
