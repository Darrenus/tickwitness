# ADR0034: Keep native computation separate from original research publication

Date: 2026-11-07 (Asia/Singapore). Status: implementation under review, S10-02b.

## Context and decision

S10-02a can reverify an original attempt after acknowledgment loss. Real managed execution additionally needs a durable association and publication fencing. Moving the synchronous `run_reduction_input` into a worker would grant the worker research-ledger writes and let a stale process publish after losing its Job owner.

Keep the existing one-attempt snapshot/event and Catalog schema1. Add a distinct execution spec and deterministic versioned original reservation nonce derived from its immutable Job ID. The current coordinator alone reserves, binds intent/preparation CAS and publishes. Duplicate nonce admission always refuses another execution. The worker receives a bounded path-free ReplayInput and credentials, directly computes an existing ReplayResult, and has no Catalog or research writer capability. Same-user trusted code remains the operational boundary.

The coordinator independently reopens source/preparation and actual original ledger, rebuilds accounting and receipt, checks its current owner/version/credentials/lease immediately before each write, and stores the exact original research receipt as the Job result. Catalog admission checks repeat ownership and clocks after potentially blocking reads. No research publication transaction spans a native process or pretends to cover both stores.

Do not overwrite a possibly committed original outcome after readback/acknowledgment failure. Leave those durable facts available for explicit read-only observation and later acknowledgment recovery. Actual reruns require a new original slot; interrupted slots remain consumed. Explicit retry and Job acknowledgment restoration remain S10-02c, within the original story scope rather than declaring #29 complete.

## Time and process decision

A renewable heartbeat is not an execution-time budget. Preserve an independent original monotonic native deadline from before launch; heartbeat cannot extend it. Invoke the native adapter directly in the owned worker process, avoiding a detached subprocess whose timeout supervisor could die with the coordinator.

Arm the worker's default OS real-time alarm from that same deadline. Python handlers can wait for C work to return, so this worker uses the default SIGALRM termination action without a Python callback. Setup recomputes remaining time immediately before arming and checks admission again. The mechanism is exercised remotely on supported Linux/macOS, including a GIL-held libc-work fixture after coordinator SIGKILL. Signal scheduling is not a hard physical real-time guarantee and the trusted adapter must retain the timer configuration.

References: [Python3.12 signal execution and timers](https://docs.python.org/3.12/library/signal.html), [Apple setitimer manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/setitimer.2.html), [Apple default signal actions](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/signal.3.html).

## Consequences

The CLI can queue and run a real native Job under its original budget, inspect its durable original nonce/attempt association, and independently recover research facts when Catalog acknowledgment is missing. Queued/failed Catalog-only facts remain unknown rather than falsely denying consumption. The comparison operation and schema1 remain compatible.

Native request size has a separate16MiB bound; it contains no owner locator or JobSpec. Known unavailable runtime and oversized encodings fail before reserve. Actual native failures consume their admitted original slot and never publish a success manifest. Failure diagnostics preserve the actual child exit or null before launch.

Research publication is admitted under the current lease; physical commit completion is not an atomic deadline across file ledger and SQLite. Strong cancellation, total resources and full orphan directory/process policy remain S10-03. Complete checkpoints, globally authenticated history, hostile-plugin isolation, external human acceptance and release are not implied.
