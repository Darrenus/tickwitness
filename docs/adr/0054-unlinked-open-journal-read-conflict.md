# ADR0054: Refuse an unlinked open optional journal as a bounded read conflict

Date2026-11-28. Status: FROZEN before the companion implementation.
Contract: [Unlinked open Job journal conflict v1](../contracts/job-journal-unlinked-read-conflict-v1.md).

## Context

PR118/source4ce real macOS3.14 core regression failed the existing live durable
cancellation controller test with a caught unaliased-file JobStoreError. The
original inner filename/inode/trace are absent; do not assert confirmed causality.
The old adapter and test were not changed by inspection diagnostics. Existing
ADR0040 handles optional rollback-journal ENOENT at open/restat. A successful open
followed by COMMIT/unlink before first fstat leaves a regular nlink0 descriptor,
a concrete missing boundary requiring deterministic remote red/green evidence.

## Decision

Extend ONLY that read-only fixed optional-journal preflight with an internal flag
set from the enclosing connection's write=False. Require first fstat REG+nlink0
and then actual named no-follow stat ENOENT before propagating the same exception
to the existing conflict9 handler. Close the FD, do not yield or open SQLite.
Any current name, replacement/relink, nonregular/aliased inode, other errno,
mandatory Catalog/lock or writer path keeps strict3. Do not infer safe absence
from link count alone or a human message. Generic regular-file checking is not
relaxed and the original controller read/cancel deadlines stay unchanged.

## Consequences and verification

Use one companion defect in ongoing quality capacity; S14's8accepted+8selected+
16uncommitted/32h forecasts do not grow. Freeze/push/read back these documents
before code. Add real COMMIT-between-open-and-fstat tests and retain remote red
on the unmodified adapter before green on the fixed source; existing open/restat,
unsafe/mandatory/replacement/write/other-errno and actual cancellation tests remain.
A reproduced mechanism explains a coverage gap, not the missing original trace.
No new retries, Job/research execution, refund/reset, schema/domain/SDK permission,
AWS qualification, M1 enablement or human acceptance is introduced. All project
execution remains remote and all earlier failures/closed evidence are preserved.
