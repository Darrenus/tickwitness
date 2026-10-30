# ADR 0029 — Execute reduction prefixes against the original live budget

Status: Proposed; S09-01b remote implementation acceptance and owner review pending.

## Context

[ADR 0028](0028-valid-prefix-reduction-inputs.md) prepares legal, byte-preserved full-origin inputs. Static preparation cannot prove that the engine actually processed warmup, or establish account, order and pending-command state at the retained end. A portable search package also cannot authorize resetting the original attempt ledger.

The existing native adapter can replay a complete prefix and return audited traces. Its observable terminal boundary is after `engine.run` and before disposal. `engine.run` may already perform end/stop actions. The adapter does not expose a complete checkpoint or an observation taken immediately before the review focus.

## Decision

Add explicit development-only execution and read-only inspection. Revalidate the complete source package and preparation, rederive the exact prefix, and open an existing live ledger. Before reserving anything, compare every source-observed reservation and every actually inventoried candidate intent, outcome and CAS object with that live ledger. A valid appended suffix is allowed; a missing, replaced or shorter observed prefix is rejected. Uninventoried baseline details remain unobserved, rather than becoming fabricated absences.

Reserve one slot from the exact original `ExecutableProtocol`. Persist the intent and four preparation artifacts before constructing the bounded engine. Replay the prefix from the original snapshot once, with the original specification, account, strategy, seed and limits. Do not restore a snapshot, replay a hidden warmup run, advance the clock to settle EOF, or reuse an earlier reduction's state.

Independently audit the actual `ReplayResult` with `evaluate_replay(prefix_input, result)`. Bind the original starting account, complete retained input coverage, warmup coverage, fill/fee accounting, order lifecycle, final account and explicit open-order/pending-command projection. The boundary is exactly `after_native_run_before_dispose_v1`; it is neither pre-cleanup state nor a focus checkpoint. Cash-lock evidence proves nonnegative components and `free + locked = total`, without certifying an independent margin-lock algorithm.

Persist an incomplete but internally valid replay as incomplete. It cannot become an eligible reduced finding. Invalid traces or accounting consume the reserved attempt and produce a failure where publication is possible. A late publication error or inconsistent returned ID is outcome uncertainty: preserve the committed or unfinalized attempt, return no success, and do not overwrite, rerun or refund it.

Inspection reconstructs the preparation from saved CAS, matches the supplied original source and live ledger, reloads the committed reservation/intent/outcome, and recomputes the state audit. It performs no execution, reservation, repair or recovery. [Reduction Execution v1](../contracts/reduction-execution-v1.md) defines the interfaces and limits.

## Consequences

Real installed acceptance freezes a new five-slot qualification protocol before any run: baseline in slot1, original search candidates in slots2/3, then two reduction prefixes in slots4/5. The exported source remains an immutable observed prefix while the same live ledger grows. A sixth execution is rejected. The committed three-slot alpha source is never granted fresh slots or reconstructed into a new live ledger.

The native fixture covers a partial fill with an in-flight cancellation at EOF and a longer prefix named `filled-cancel-rejected`. The longer prefix fills both lots before the same input step rejects the cancellation; it finishes with two lots, two units of commission and no pending command. A longer prefix does not guarantee cancellation success. The delayed book step precedes the cancellation window; the following trade step matches before the existing engine drains the command. Acceptance checks the two fill references and the exact fill-before-rejection ordering, without changing engine semantics. Core-only acceptance tests rejection and read-only boundaries without inventing a native counterexample. Ubuntu, macOS and actual source-archive/wheel chains run the real native lifecycle remotely.

This completes the execution/state-audit part of S09-01 only when remote evidence is accepted. It does not provide a checkpoint, a complete hidden engine state, a reduced predicate, witness preservation, automatic search or any minimum-counterexample claim. S09-02 and S09-03 remain separate. External human attempts stay `0 / PENDING`, and there is no release authorization or global ledger authenticity claim.
