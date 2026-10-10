# Research data quality task package: Q27–Q29

Baseline: main `557c93e4f62a18705f7a4fb4892d756d3f747c94`, after Q26.
The owner's 2026-10-10 instruction authorizes this package's implementation,
in-scope repair, tests, commits, push, PR, independent final-candidate review,
conditional squash merge and exact-main CI verification, in priority order.
It does not authorize production activation, formal releases or live trading.

The external review used Q23 main `8f68b1361034bb08f4cc1b2d118353d1a1b1a9ba`.
The three concerns were checked again against the newer baseline. The calendar
support gap and lower-level no-overwrite gap remain. The original review did
not demonstrate ordinary collection losing data or a real strategy PnL error.
Existing per-symbol pair verification, registration, NONE-only PIT, same-session
intraday execution, and saved artifact identities must be retained.

## Order and completion

1. **Q27 — bundled exchange calendar and explicit support status.**
2. **Q28 — immutable market-bar publication and forward recovery.** A small
   design-only prerequisite PR must first approve invocation-owned staging
   cleanup under the repository's destructive-operation gate; implementation
   starts only after that contract is in main.
3. **Q29 — unadjusted return-basis disclosure and bounded event-window checks.**

Read-only investigations may overlap. Each implementation starts from the
verified main resulting from the preceding task. Each final candidate needs
an independent review, successful natural PR CI for that version, a verified
PR head/base and squash merge, then terminal successful CI on the exact main
commit before proceeding. Existing classification and ten functional test
partitions remain authoritative; no forced reduced tier or unrelated CI rewrite.

## Q27: calendar and special-session authority

**Goal:** distinguish supported normal/special sessions, exchange closures,
known but unqualified early closes, and missing calendar coverage before a
misleading generic timestamp mismatch.

**Design:** a bundled immutable 2025–2027 NYSE equity core-session schedule,
with version, source, publication date and retrieval date. Include regular
holidays, observed dates, all published early closes and the January 9, 2025
emergency closure. Resolve the exchange date first, then enforce the existing
independent exact-date OpenD provider qualification and full-sequence check.
See [the Q27 contract](contracts/us_rth_calendar_v1.md).

**Dependencies:** current normalization and sealed normal/early-close profile
evidence; official exchange schedule. No runtime network or new dependency.

**Defaults:** America/New_York; normal 09:30–16:00; qualified early close
09:30–13:00. Closed/out-of-range dates refuse RTH conversion. Known unqualified
early dates return `PROVIDER_UNVERIFIED` with the exact reason and source.

**Acceptance:** correct multi-year classification, observed holidays and
coverage edges; preserved sealed timestamp mappings and DST handling; an
unqualified 210-row response reports the missing provider qualification and
cannot be admitted by changing row shape; normal partial responses still fail.

**Exclusions:** new live qualification, accepting 2025-07-03 or future special
dates without that evidence, arbitrary calendar years, other markets, option
hours, ALL/legacy/daily behavior, archive rewriting or new PIT-time arithmetic.

## Q28: immutable publication and bounded recovery

**Goal:** make market-bar Raw/Curated final paths non-overwritable at the store
boundary, and give interrupted pair/registration work a forward recovery path
that preserves original evidence.

**Design:** serialize to a unique sibling staging file, close/flush it and
publish through a no-replace atomic filesystem operation. An existing target
is a conflict, even when the caller repeats the same run ID. Clean up only the
staging file owned by this invocation. Keep existing path layout and pair
fact verification/registration; publication of two different files is not a
claim of a physical multi-file transaction. Recovery selects a named original
terminal run and exact expected Raw paths, verifies their identity, and
replays available Raw into a fresh run through the normal normalization,
publication and registration path. Preserve original files and terminal run
history; bind the recovery result to its source run.

**Dependencies:** Q27 main, the existing per-symbol snapshot contract and
lifecycle lock, plus the separately approved exact staging-cleanup binding.

**Defaults:** refuse overwrite; offline recovery, explicit source manifest,
new run ID; no scanning to adopt arbitrary files. A missing source manifest,
unreadable or mismatched Raw, or unresolved lifecycle lock is a clear refusal.

**Acceptance:** repeated/conflicting destination writes cannot change original
bytes; interrupted serialization exposes no final partial file; publication
race has one winner; incomplete pairs and failed catalog registration never
become success; a valid retained Raw can produce a new registered complete run
without refetching OpenD, mutating original files or reclassifying original
failure as success. Existing normal collection and audit paths still work.

**Exclusions:** runtime-data deletion/rollback, replacing existing Curated,
rewriting terminal history, automatic stale-lock removal, repair of arbitrary
orphans without original identity, distributed transactions or redesign of
options/calendar stores.

## Q29: return meaning and corporate-action windows

**Goal:** make NONE price-return and simulated-account semantics visible in
Dataset, reports and research screens; distinguish unknown event coverage from
a known event-window intersection.

**Design:** unified current-reader disclosures, plus a small separate versioned
assessment over verified saved research inputs and their actual feature,
target, holding or benchmark windows. An optional explicit finite event/date
restriction list has its own content identity and provenance. It is a
retrospective research-quality screen, not historical corporate-action PIT
authority. A machine-readable command can act as a gate by returning nonzero
when declared event windows intersect. Results reference original source IDs;
old reports and calculation bytes stay intact.

**Dependencies:** completed storage/calendar tasks as the accepted baseline;
existing Dataset/experiment readers and actual label/trade window evidence.

**Defaults:** PIT remains NONE-only. No list means coverage `UNKNOWN` and
`NOT_CHECKED`; a finite list means `PARTIAL`, even when empty or nonintersecting.
State explicitly that split-share adjustments and cash-dividend accounting
are absent. Listed intersections are disclosed as restrictions; no silent
sample deletion. A date-only event is a conservative date restriction, not a
fabricated exact corporate-action instant.

**Acceptance:** unknown/partial/no-match states cannot imply full clearance;
synthetic split-crossing price windows are identified without inventing total
returns; an event before actual entry is not falsely labeled an exact crossing
of a later same-session trade; differing symbols and disjoint windows do not
match; current screens and CLI show the basis; old IDs, saved JSON and replay,
NONE-only guard and same-session forced-flat behavior remain compatible.

**Exclusions:** QFQ/HFQ unlock, total-return engine, split-share or dividend
accounting, commercial event feed or complete-coverage claims, inferred splits
from price jumps, automatic cohort changes or historical artifact migration.
