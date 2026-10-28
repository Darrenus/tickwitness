# ADR 0028 — Bind reduction inputs to a complete source prefix

Status: Proposed; S09-01a [remote implementation acceptance](../planning/sprint-09-status.md#s09-01a-远端验收记录) passed, awaiting owner acceptance of [PR #95](https://github.com/Darrenus/tickwitness/pull/95).

## Context

[S09-01 / #25](https://github.com/Darrenus/tickwitness/issues/25) needs legal reduction operators before a budgeted reducer can search for simpler counterexamples. Removing an order-book delta can break sequence continuity. Removing an earlier trade can change fills, commissions, account balances and pending commands even when the displayed book looks identical.

The current Nautilus adapter does not advertise `CHECKPOINT`. An L2 snapshot contains market state; it does not contain the strategy, account, open orders, fills, pending commands or engine state needed to resume a replay. The existing synthetic counterexample makes this concrete: before capture 4, capture 3 has already partially filled an order and issued a cancellation.

## Decision

Deliver S09-01a as development-only input preparation. Authenticate a complete portable search-evidence package and exact source bundle/report pins, then select an actual completed, audited false witness. Reconstruct the original protocol, replay specification, assumptions and scenario before deriving any input.

Allow three explicit operators: choose a review focus, retain a contiguous prefix through an actual source capture, and reduce the selected witness's additional delay within the original frozen assumption range. A full-length, unchanged-delay no-op is legal. Focus changes the review boundary; execution input still begins at the original initial snapshot and retains every warmup event. No intermediate event is removed, recoded, reordered or renumbered.

Rederive the complete candidate scenario from the complete original source before cutting the prefix. Bind the recipe and prefix descriptor to the complete source semantics, scenario and original engine/specification identity. A changed scenario gets a new context even when part of its bytes happens to remain equal. The reduction context has its own identity; it is not a replacement catalog dataset or the original derived view.

The output is a portable, immutable four-file preparation bundle. Verification independently recomputes every saved role from the authenticated source. Rehashing a modified descriptor or normalized input cannot make it valid. Exact format, limits, CLI and scope are defined in [Reduction Input v1](../contracts/reduction-input-v1.md).

Preparation requires a future full replay from the original start. It does not materialize or verify an engine initial state, run native code, reserve an attempt, evaluate a reduced predicate, establish witness preservation or certify a checkpoint. There is no checkpoint import or resume path in this profile.

## Consequences

Shorter right prefixes can reduce future replay input size while preserving source ordering and the necessary warmup history. They can also end with outstanding orders or commands; preparation makes no completion or conclusion claim. S09-01b must qualify actual prefix replay and its state semantics before #25 can close. S09-02 remains responsible for budgeted local search and verified conclusion preservation; no global minimum or monotonic delay-to-PnL assumption follows from this decision.

The core-only installed acceptance reuses the committed counterexample and clean-control evidence, verifies relocated bundles, and guards native, original stores, network and budget access. Tests, installation, builds and formatting run remotely. Existing external alpha attempts remain `0 / PENDING`; CI, owner and AI activity do not count as external attempts, and [#24](https://github.com/Darrenus/tickwitness/issues/24) remains open.

Future checkpoint support requires a separate capability and a complete, verified state contract bound to the scenario's prefix semantics. A book snapshot or queue observation named “checkpoint” does not satisfy that requirement.
