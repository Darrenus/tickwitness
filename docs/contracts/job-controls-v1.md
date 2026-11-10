# Job controls v1

Frozen for S10-03 implementation, 2026-11-10 (Asia/Singapore). Owner merged [PR104](https://github.com/Darrenus/tickwitness/pull/104), accepting S10-02c at `445df01f1f30c77f8161172a0c96b8827be6b4b9`. This document freezes intended semantics before implementation; passing evidence will be recorded on its implementation PR. [Story30](https://github.com/Darrenus/tickwitness/issues/30) remains open. External humans **0 / PENDING**.

## Compatibility and control authority

A separately frozen policy opts one existing QUEUED Job into controls. Policy identity binds the exact Job and limits; repeated identical policy is idempotent, changed policy conflicts. Current coordinators automatically enforce it. Unconfigured Jobs preserve their historical descriptors, schema1, snapshots, events and result bytes. Quiesce older coordinators before enabling policies. Control is local to this Catalog and its one Job attempt, not global cancellation of the same descriptor in another Catalog or of a research protocol.

Cancellation acceptance is durable intent. Confirmed stop requires actual owned worker/group termination and safe scratch cleanup. The original Catalog enum remains unchanged: live-lease stop can become FAILED with a distinct cancellation/deadline/resource code; expired-lease settlement remains LOST. A separate control receipt reports actual stop, cleanup and Catalog facts. No fabricated heartbeat or weakened terminal expiry invariant is permitted. Queued cancellation starts no worker and reserves no research slot; while another coordinator owns the Catalog, intent may remain visibly pending until serviced.

## Fixed deadline and supported ceilings

The immutable policy contains total admission wall time, worker CPU seconds, maximum single-file size, open file descriptors and cleanup grace. Defaults are120 seconds,60 CPU seconds,8 MiB per file,128 descriptors and5 seconds cleanup. Total time starts before claim/preparation and never renews with heartbeats. Every phase, completed blocking verification and irreversible admission rechecks the same live monotonic deadline. Persisted monotonic clocks are never resumed. Worker default OS termination uses the earlier of remaining total time and the original native deadline.

The deadline fences new execution/publication admission. Synchronous verification, kernel IO and fsync can delay observed stop or terminal confirmation; it is not a universal physical real-time termination promise. An already admitted commit is never undone after a late acknowledgment.

A stdlib-only child bootstrap applies supported OS CPU, single-file and descriptor limits before project/native imports, without parent `preexec_fn`. Unsupported requested enforcement is refused before claim/research reservation. These controls do not certify RSS, aggregate scratch bytes, per-UID process quota or global storage limits. Existing IPC bounds and original research attempt/event/native-wall limits remain independent and cannot be enlarged or refunded by controls.

## Cancellation versus irreversible publication

A separate per-Job gate serializes accepted requests against short reservation/start admission and the first irreversible success admission. The controller reads Catalog before this gate and never waits for Catalog ownership or the research family lock while holding it. Coordinator order is Catalog ownership, original family, control gate.

An immutable cancel request binds policy, Job, explicit key and UTC request time. Same-key repetition reads the first request without another event/write. A durable publication marker is created before native research publication plus Catalog completion, or before comparison/ACK completion; that admitted section holds the same gate. Marker observed means cancellation is too late or publication is unconfirmed, never accepted cancellation. The marker itself does not prove a research receipt exists. Accepted cancellation cannot later publish a successful result in that controlled execution. A reservation/write already admitted when cancellation races may remain consumed; there is no refund or cross-store rollback.

## Owned processes and temporary products

The controlled supervisor retains its current unreaped child identity until group signaling, then reaps and checks group disappearance. It never signals a recovered PID alone. Permission errors, remaining groups or ambiguous identity retain diagnostics and unconfirmed stop status.

Only the same-user no-follow `.job-controls/JOB/workspaces/ATTEMPT/scratch` namespace is reclaimable. Immutable workspace seals and inherited lifetime-lock descriptors bind ownership. Closing a coordinator's descriptor does not unlock an orphan's inherited lifetime. Normal deletion follows confirmed stop and lock absence; uncertainty retains scratch rather than deleting it unconditionally.

Explicit reclamation owns the Catalog, reconciles orphan state, validates policy/attempt/seal/path and requires a free lifetime lock. It never signals stale PIDs, follows workspace links, deletes research/input/Catalog roots or resets unknown/partial journals. Identity and bounded control diagnostics are retained after scratch removal. This is trusted built-in execution, not containment of hostile or escaped processes.

## Qualification and remaining scope

New controls qualification freezes a distinct, explicitly titled original eight-slot lifecycle before baseline: source1–3, native cancellation4, total deadline5 despite genuine heartbeats, enforced resource failure6, cancellation-wins race7, publication-wins race8. Cases use an explicit retry successor chain under the same original ledger. Policies freeze before claim. Committed outcome recovery after exhaustion adds no ninth slot or worker. Historical five/eight/eleven-slot, golden and PR94 evidence is unchanged.

Remote core, Ubuntu, macOS and actual-source/wheel profiles retain raw policies, requests, admission/control receipts, Catalog events/results, original slots/intents/CAS, process/IPC/limit/workspace evidence, transcripts and file manifests. Core labels transport fixtures and lack of native evidence honestly. Cancellation latency is measured from request start to independent terminal observation using one observer's live monotonic clock; measured samples are not universal latency bounds.

No automatic retry, full engine checkpoint, distributed/global cancellation, hostile-owner authenticity, physical power-loss guarantee, release, adoption or profit claim is introduced. Project tests, formatting, typing, builds, installation and native execution run only on remote CPU CI. CI and AI review do not count as external human reproduction.
