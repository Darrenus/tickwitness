# ADR0035: Record retry and acknowledgment as immutable followup Jobs

Date: 2026-11-08 (Asia/Singapore). Status: S10-02c implementation under review.

## Decision

Preserve the old single-attempt Job and its terminal. A new explicit followup descriptor embeds the exact original native spec, actual parent, mode and idempotency key. One retry successor per parent is admitted in a short Catalog transaction; acknowledgment records are separate and never become native parents. Return the original verified outcome inside a distinct resolution wrapper, so successful execution of acknowledgment cannot turn a committed research failure into a successful research claim.

Use a bounded immutable original-ledger family journal and a shared nonblocking family lock. SQLite-only successor checks cannot stop a stale Catalog or second Catalog from branching. All current native publishers hold this shared lock through reserve, worker, audit, research publication and Job completion. Claims precede actual original reservations; partial commits fail closed and never imply an unconsumed slot. Quiesce pre-upgrade coordinators. This extends trusted same-user coordination, not hostile-owner isolation or authenticated global history.

Retry checks all actual family nonces/outcomes before admission. Existing committed receipt or failure is independently reverified and acknowledged without native execution. A real retry consumes a new original-protocol slot and replays from the frozen origin. No complete checkpoint is available. Acknowledgment reads original records and journal without research writes, and only commits a new Catalog Job result/event under current ownership and lease. Postcommit response loss leaves independently readable success; repeated same request returns it without another event or execution.

## Consequences

The old terminal, schema1 and result bytes stay compatible. New wrappers distinguish replay from acknowledgment and bind the actual original dispatch. There is no atomic transaction spanning shared metadata, original outcomes and Catalog, nor automatic repair/refund. Unknown or inconsistent history fails closed. Current remote installation/fault evidence belongs in the implementation PR. Strong cancellation, total resources and complete orphan cleanup remain S10-03; external human reproduction remains0/PENDING.
