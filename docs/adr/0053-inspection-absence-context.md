# ADR0053: Keep inspection absence context at the CLI adapter boundary

Date:2026-11-28. Status: FROZEN before implementation, S14-02a/F02/#41.
Decision contract: [Inspection absence context v1](../contracts/inspection-absence-context-v1.md).
Commit/push/read back this ADR and contract before product changes.

## Context

After owner acceptance of PR117, baseline missing-object diagnostics have their
own narrow error contract. Existing inspect-experiment/inspect-attempt still
flatten distinct requested-target/dependency failures into code/message. Storage
already distinguishes typed NotFound from integrity refusal, and the application
owns protocol-reference and committed-attempt semantics. SDK v1 excludes these
executable-v2 commands. There is no verified demand for an additional transport.

The attempt ledger's NotFound means no verified committed CAS/slot closure, not
proof that research never ran. A valid unfinalized reservation is successful
inspection with consumed budget. Dataset inspection legitimately opens SQLite
read-only, unlike portable baseline bundle verification.

## Decision

Add typed context only around the existing CLI's real lookups, preserving every
existing code/exit and service call order. Use narrow read-only delegating
registry/dataset adapters for the existing inspect_experiment service, and a
whole committed-attempt boundary for inspect_attempt. Do not duplicate application
validation, extend application ports or change infrastructure exception APIs.

Carry fixed reason/command/requested_id/lookup, plus resource_id only when known
from that actual call. Constructor context has no resource_id. Preserve cause and
message without parsing human text. All non-NotFound paths remain untouched.
Do not add budget or recovery authority to an error projection.

Select forecast8h once from parentS14-02's12h within originalS14 32h; accepted8h
plus this selected8h leaves16h uncommitted. No actual-effort claim, transport work
or additional human participant is inferred. #40's accepted first slice and its
uncommitted parent capacity remain separately tracked; only this new functional
slice is active.

## Consequences and verification

Current readers and schemas stay compatible; successful receipts and SDK v1 are
unchanged. Existing ambiguous absence classification stays bounded to its current
meaning, including CAS/slot closure and trusted-root prechecks. Context is not an
OS absence proof, semantic receipt or malicious-code sandbox.

Remote real-filesystem/CLI tests cover six lookup boundaries, dependency identity,
priority, ordinary integrity/IO refusals, CAS orphans, consumed unfinalized and
finalized attempts, invalid inputs and unchanged other routes. An installed bounded
driver uses only disposable copies of existing synthetic smoke state, permits
existing read-only SQLite and denies new research/native/worker/network actions.
Persistent evidence bytes stay intact; SQLite WAL/SHM runtime activity is stated
rather than hidden by an unsupported filesystem-no-write claim.

M1DISABLED, human securityNOT_PERFORMED and external-human0/0/PENDING remain.
No protocol budget reset/refund, committed-result re-execution, AWS Start/new
qualification, old export/ACK, outreach, listener or release is authorized.
