# ADR 0031 — Compare committed original and reduced witness evidence

Status: Proposed; S09-03 implementation and remote qualification in progress, 2026-11-05.

## Context

[ADR 0030](0030-bounded-local-reduction.md) retains a best-known smaller input only when its actual endpoint keeps the original numeric criterion false. A reviewer still needs to see which events were retained or removed, which receive clocks changed and where the recorded executions differ. A shorter run has its own EOF and valuation horizon; its final account is not a captured intermediate state of the longer original run.

The left execution is the original false **scenario witness**, rather than the protocol baseline. Existing [scenario comparison](../contracts/scenario-comparison-v1.md) provides a useful trace projection, but its baseline association and claim-integrity evaluation are not the authority for this comparison.

## Decision

Add a read-only `ReductionComparison` of the source-selected original scenario and one existing committed reduction run. Reaudit the complete source and observed original live prefix, both actual receipts and raw replay results, the original scenario evaluation, the reduced state audit and its preservation assessment. Keep the original frozen numeric criterion; reject invalid bindings or accounting rather than classifying them as unknown.

Show actual stable references for the origin prefix, warmup, review interval, removed suffix and every changed retained receive clock. Include complete original derived events for the removed suffix and exact canonical line hashes. Derive references from actual source positions, including capture sequences that start above one. Current replay preflight continues to reject gaps within a stream.

Reuse `compare_scenario_traces` and its declared `coupled_stress_business_projection_v1` exclusions without changing old formats. Retain raw differences, business-projected differences, original values and per-channel references. Compare whole recorded runs, including their unequal EOFs. The fixed channel order and per-channel ordinal order do not claim a global earliest event or establish causality. Do not hide final-state differences or infer a shared terminal snapshot.

Display each run's own original-criterion observation and mark. `both_false_witnesses` is true for preserved, false for not preserved and null for not evaluable. Do not report a numeric effect as comparable across different valuation horizons, extend the source predicate domain, issue a baseline flip or certify a minimum.

Export a bounded canonical report in a content-addressed envelope. Its comparison ID hashes the report, not the envelope. Verification pins the requested reduction run, source bundle/report and comparison identity, then independently rebuilds the entire report from source and committed live evidence. Rehashing a modified observation does not replace this audit. JSON output remains canonical without a trailing newline; a Markdown view exposes the same facts for review.

[Reduction Comparison v1](../contracts/reduction-comparison-v1.md) defines the exact fields, projections, CLI, failure taxonomy and scope. Comparison does not reserve, replay, publish, reset, repair or resume anything. Existing exhausted ledgers remain readable, and old preparation, execution, state-audit and preservation flags retain their original meanings.

## Consequences

The feature provides a verifiable review artifact for already executed original and reduced cases. It distinguishes integrity reauditing from another native execution and identifies the source record behind every displayed change. A standalone comparison envelope does not authenticate its author, reconstruct missing original records or provide S10 recovery authority.

Installed qualification reuses the actual eleven-slot S09-02 lifecycle from the same remote job. An installed core-only verifier compares seven main candidates and the actual run retained after cooperative cancellation. Read-only guards prohibit native imports/workers, reservation, publication, writable ledgers, old research stores, network and SQLite. Semantic forgeries, wrong source pins, missing records and corrupt CAS must fail while the original byte tree and eleven slots remain unchanged.

The core-only profile has no native positive case and reports only its real refusal boundaries. All new comparison actions have `native_execution=false`; three separate installed profiles may reuse actual native source records. Artifacts retain upstream bytes, command transcripts, exports, Markdown, independent verification receipts, runtime identity and hash manifests. Only remote results may establish qualification success.

Owner acceptance, external human reproduction, S10 recovery and any new release remain distinct gates. External human attempts remain `0 / PENDING`.
