# ADR0037: Keep resource observations separate from research authority

Date2026-11-12 Asia/Singapore. Status: frozen before implementation, owner acceptance pending.

S10 controls constrain execution but do not explain actual cost. A configured limit is not a measurement, and missing metrics after a crash must not become zero. Preserve original Job/control/research bytes, and publish a bounded immutable operational report in a separate namespace. Actual report snapshot bindings remain historical after reconciliation; a current read view must distinguish the two.

Use the trusted anchor's wait4 accounting for its one owned compute child, sent through an independent bounded nonblocking pipe. Do not infer child cost from global coordinator RUSAGE_CHILDREN or burden strong cancellation with another process wait. Units and kernel scope remain explicit. Reuse the existing safe cleanup traversal for logical regular-entry bytes rather than scanning scratch twice. Unknown/partial measurements do not change Job or research results.

A separate metadata-only preview reads only a descriptor and control policy. Existing limits, unknown cost predictions and conditional research-slot need are distinct; none grants execution authority. Research reservations, audited replay results, processed inputs and predicate evaluations retain separate meanings. No calibration means no CPU/memory/time/disk prediction.

The [resources contract](../contracts/job-resources-v1.md) freezes exact formats, process/IO boundaries, measurement and unknown semantics. Four existing remote controls profiles qualify the new observations without another research attempt, worker or budget. S11-02 deletion and S11-03 fault-budget work remain separate. External humans remain0/PENDING.
