# Destructive Purge Contract Draft

> **Status: superseded design record.** The reviewed Safe Purge v0.1 behavior
> is defined by [contracts/safe_purge_v01.md](contracts/safe_purge_v01.md).
> This file remains as the original non-normative review input.

## Safety Objective

A future purge must remove only immutable runtime artifacts selected by a
reviewed lifecycle policy while preserving evidence, referential integrity,
point-in-time semantics, and recovery expectations. Convenience is never a
reason to bypass verification.

## Proposed Two-Phase Flow

1. **Plan locally:** resolve a typed scope and exact artifact identities;
   calculate dependencies, affected rows/files/bytes, retained evidence, and
   refusal reasons. No mutation occurs.
2. **Approve a sealed plan:** serialize a deterministic plan ID and content
   hash. The operator reviews the complete plan, then provides typed
   confirmation containing the plan ID.
3. **Re-verify:** immediately before execution, prove that every target and
   dependency still matches the sealed plan. Any drift fails closed.
4. **Execute under an exclusive lifecycle lock:** move eligible artifacts to
   a quarantine area on the same volume; update lifecycle metadata through a
   dedicated service transaction; never issue arbitrary SQL.
5. **Verify and record:** verify survivors and metadata, write an immutable
   purge result linked to the plan, and retain a recovery deadline. Physical
   deletion from quarantine is a separate, owner-authorized lifecycle step.

## Required Typed Scope

A plan should require dataset kind, source, exact symbol/scope, parameter
combination, inclusive date range, artifact layer, and reason. Empty or broad
wildcard scopes fail closed. Paths supplied by users are never accepted as
targets; the service resolves artifact identities from verified metadata.

## Mandatory Refusals

The service must refuse a plan when it cannot prove ownership, path
containment, exact artifact identity, dependency closure, active-run safety,
or compatibility with retained manifests and verified derived artifacts. It
must also refuse credentials, settings, source code, formal release assets,
unknown files, and artifacts outside configured runtime roots.

Canonical builds, Datasets, and Catalog snapshots that depend on candidate
Raw/Curated data require an explicit reviewed retention rule. No cascade is
implicit. OpenD availability is irrelevant and must not relax refusal logic.

## Review Questions Before Implementation

- Which artifact classes are legally purgeable, and which evidence is
  permanently retained?
- Is quarantine-and-expiry sufficient, or is backup proof required?
- What dependency graph is authoritative across Raw, Curated, Canonical,
  Dataset, and Catalog artifacts?
- Which owner authorization and independent review evidence is required?
- How are interrupted execution, rollback, and partial filesystem failures
  represented without claiming success?
- What Windows locking and same-volume atomic-move guarantees are required?

Any implementation will require a separate high-impact PR with explicit
schema/storage/lifecycle visibility, adversarial tests, migration and recovery
analysis, and repository-owner authorization. This document authorizes none of
those mutations.
