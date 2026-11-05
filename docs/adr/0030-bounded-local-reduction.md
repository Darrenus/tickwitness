# ADR 0030 — Search finite reduction neighborhoods on the original budget

Status: Proposed for owner acceptance; S09-02 implemented and remotely qualified, 2026-11-01. Actual runs and artifacts are recorded in the [Sprint 9 acceptance record](../planning/sprint-09-status.md#s09-02-远端验收记录).

## Context

[ADR 0029](0029-origin-prefix-execution.md) executes and audits a full-origin prefix against the existing source protocol. It does not decide whether that prefix retains the original false numeric criterion, or select a smaller input automatically. EOF may remain incomplete, and changing a receive delay can change which input step settles a cancellation.

## Decision

Freeze a canonical finite plan against one complete authenticated false source witness. Keep the review focus fixed. Try integer delay halving before removing one actual tail event; accept only a strictly smaller point whose actual completed, valued result still makes the original numeric criterion false, then restart its neighborhood. Initial best references the source witness and consumes no new slot.

Reuse the original protocol, live attempt ledger and exact per-attempt engine limits. Keep the source-observed prefix immutable and revalidate it before execution or inspection. A new plan never restores portable slots, extends old search budgets or refunds a failed attempt. Additional step and between-candidate elapsed caps only narrow admission. They do not provide a hard total wall deadline or managed-storage quota.

Separate PRESERVED, NOT_PRESERVED and NOT_EVALUABLE. Invalid evidence fails validation. Execution failure or an unfinalized attempt has no fabricated assessment. Bind the assessment to the actual receipt, raw result and independently rebuilt state audit. Original finding/predicate IDs provide provenance; applying their numeric criterion on a reduced horizon does not rewrite their quantified candidate domain, evaluate a baseline/source claim or certify a minimum.

Persist header, dispatch/nonce, original attempt link, exact assessment, cancellation and stop in an append-only reduction namespace. Reuse existing strict IO through protected adapter hooks while keeping original search paths and record types unchanged. Rerunning an already started plan inspects its committed/partial history; it does not resume, repair or execute again. Late publication uncertainty preserves existing committed outcomes.

Cancellation writes an idempotent marker without waiting for the coordinator lock. The current bounded attempt commits its real outcome and assessment before the next candidate boundary observes cancellation. This is cooperative stopping, without native worker killing or S10 recovery semantics. A terminal stop is immutable; a late cancellation request cannot replace it.

[Reduction Search v1](../contracts/reduction-search-v1.md) defines the requests, persisted records, CLI and explicit scope. Read-only inspection rebuilds the complete source, plan, traversal and each assessment from actual CAS evidence, without another reservation or native execution.

## Consequences

The reducer provides a reproducible best-known simplification and its checked neighborhood, including unknown candidates and actual stop reasons. It never certifies local or global minimality. Existing preparation and state-audit formats retain their original flags.

Installed qualification freezes a new eleven-slot synthetic lifecycle and numeric criterion before executing anything. Three source slots are followed by one real attempt with a controlled cooperative cancellation hook and seven main reduction attempts; an additional campaign must stop at the same original budget without a twelfth slot. The main path includes preserved, non-preserved and incomplete observations. Core-only, Ubuntu, macOS and actual source-archive/wheel paths produce separate remote evidence. The old three-slot golden, five-slot execution qualification and original external handoff remain unchanged.

External human attempts remain `0 / PENDING`. Owner acceptance, S09-03 comparison, S10 recovery and any new release require their own evidence.
