# Managed native reduction Jobs v1

S10-02b, implementation under review, 2026-11-07 (Asia/Singapore). [Story #29](https://github.com/Darrenus/tickwitness/issues/29), [ADR0034](../adr/0034-coordinator-owned-native-jobs.md), [Sprint10](../planning/sprint-10-status.md). Owner merge of [PR102](https://github.com/Darrenus/tickwitness/pull/102) accepts the earlier [read-only attempt recovery](reduction-attempt-recovery-v1.md). This extension adds real native execution; explicit retry and Job acknowledgment recovery remain subsequent S10-02 work. External human reproduction remains **0 / PENDING**.

## Identity and original budget

The new allowlisted operation is `execute_reduction_input_v1`. Its `reduction_execution_job_spec_v1` keeps the existing exact envelope fields: `kind`, `schema_version=1`, `operation`, `request`, `lease_duration_ns`. Request fields are exactly `preparation`, `expected_preparation_id`, `expected_bundle_id`, `expected_report_id`, `input_root`, `source_evidence`, `runs`, `split`, `engine_runtime`, `restart_mode`.

The three pins are lowercase SHA-256 identities. Preparation/input/ledger paths are absolute owner locators; source evidence is relative without traversal. `split=development`, `engine_runtime=coordinator_interpreter_v1` and `restart_mode=frozen_origin_new_attempt_only_v1` are fixed. There is no arbitrary interpreter/command, checkpoint or replacement budget field. The worker uses the coordinator's interpreter and the original pinned engine profile. Catalog and input/preparation/ledger trees must be disjoint; native input/preparation and the writable ledger must also be disjoint.

Job ID remains the canonical descriptor's SHA-256. Research dispatch nonce is the first32 hex characters of SHA-256 over canonical `{kind:"reduction_job_dispatch_nonce_v1",job_id:JOB_ID}`. Its versioned derivation and complete descriptor are durable before reservation. The original ledger's actual reservation carries that nonce; it is not the separate Job attempt nonce or lease token.

Every native invocation requires a new, actual slot under the frozen original protocol. Authorization verifies the observed source prefix against the original live ledger, refuses any already committed matching nonce, reserves once through the existing named reservation lock, and binds the exact intent and four preparation CAS objects before worker launch. Errors do not refund the slot. A duplicate Job in a second Catalog cannot use the same original nonce for another execution. Different locator descriptors produce different Job IDs, but cannot increase the original protocol's attempt budget or reconstruct a live ledger from portable evidence.

Resubmitting an identical descriptor returns its existing Job. Terminal `run-job` calls never start another worker. Snapshot/event version1, one Job attempt, immutable terminal states and SQLite schema1 remain compatible with [comparison Jobs](job-lifecycle-v1.md). This release does not reset, retry or resume a failed/lost Job.

## Coordinator authority and publication

Only the current coordinator writes either the Catalog or the original research ledger. Source/preparation verification is shared with synchronous reduction execution. Before reserve, intent binding and final research publication, the coordinator checks its exclusive owner PID/FD/incarnation, current Job version, attempt/token and current UTC/monotonic lease. A potentially blocking Catalog read is followed by fresh ownership and clock checks; waiting for SQLite cannot silently spend the remaining publication authorization window.

The native worker returns only an existing raw `ReplayResult`. The coordinator reopens pinned source/preparation and original ledger, independently reconstructs the state audit and original `reduction_run_receipt_v1`, verifies current publication authority and publishes that one immutable original outcome. Preparation/result/audit CAS objects precede the immutable outcome name. After exact readback and independent stored-run inspection, the exact original receipt is stored as the Job result BLOB with snapshot/event in one Catalog transaction. No second research-manifest format is introduced.

Publication is authorized at admission time. A physical disk commit can finish after that admission window; there is no hard realtime fsync guarantee or atomic transaction spanning the file ledger and SQLite. If research publication or readback is unconfirmed, the coordinator propagates the error without publishing a compensating failure or silently rerunning. A committed research result can therefore coexist with a RUNNING/lost Job and no readable Job result. Explicit orphan reconciliation can mark that Job LOST, but cannot restore its acknowledgment in this slice.

A stale version, token, incarnation or expired lease cannot admit research publication. Worker failure or death leaves its consumed original reservation/intent unfinalized; it does not create a success receipt or refund. The original receipt may legitimately say `execution_status=incomplete`; a verified native execution Job can be SUCCEEDED without certifying strategy completion, counterexample preservation or the source research claim.

## Native process, IPC and time

The distinct path-free `job_native_worker_request_v1` contains exact Job credentials and a payload with `research_attempt`, `intent`, `dataset_id`, `normalized`, `replay_spec`, `native_deadline_ns`. It contains no JobSpec, Catalog, ledger path/FD, input locator, arbitrary plugin or strategy source. Reservation nonce, original protocol, intent, normalized hash, input context and replay spec are checked before engine construction. Native request bytes are bounded at16MiB; encoded replay input must leave64KiB metadata headroom before reservation. Native result frames use the existing bounded result allowance plus64KiB; stderr remains64KiB. Comparison request bytes remain64KiB.

`job_native_result_v1` adds `replay_result` to the existing exact IPC credentials and next sequence. Heartbeat and failure frames retain their existing contract. Frames must be canonical, bounded, correctly bound and sequenced, with one terminal and actual exit0 for success. A self-reported hash alone is not authority. Known missing/mismatched native runtime is refused before reservation; actual native dependency/version is checked again by the worker.

The native worker directly invokes the built-in Nautilus adapter in its owned process group. It does not create a detached native grandchild through `SubprocessReplayAdapter`. Its renewable Job heartbeat lease and the original native wall budget are independent. The original absolute monotonic deadline is anchored before process launch and never renewed by heartbeat. Startup, request delivery, native execution and terminal IPC share that window; later independent audit/publication still requires the current Job lease.

The worker also arms its own default OS SIGALRM real-time timer from the remaining absolute deadline, rather than relying on a Python signal callback or heartbeat thread to interrupt C work. Alarm setup recomputes remaining time before arming and checks admission again. This bounds the trusted single native process after coordinator death, subject to OS scheduling/signal delivery and the trusted adapter retaining that configuration. It is not hostile-code isolation, instantaneous physical termination or complete cross-incarnation orphan reclamation. Strong cancellation, total-resource and directory cleanup policy remain S10-03.

## Read-only dispatch observation and CLI

```sh
tickwitness submit-reduction-job /owner/prepared-prefix \
  --expected-preparation-id PREPARATION_ID \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID \
  --input-root /owner/inputs --source-evidence portable/source \
  --runs /owner/original-runs --jobs /owner/jobs
tickwitness run-job JOB_ID --jobs /owner/jobs
tickwitness inspect-job JOB_ID --jobs /owner/jobs --events
tickwitness inspect-reduction-job JOB_ID --jobs /owner/jobs
tickwitness read-job-result JOB_ID --jobs /owner/jobs
```

Submit freezes the descriptor and queues the Job; it does not execute or consume research budget. Confirmation is denied before identifiers/paths/Catalog IO. `inspect-job` stays Catalog-only. For native queued/failed/lost Jobs, Catalog-only reservation/replay facts are null, not an invented assertion that nothing was consumed. Success records a structurally checked original receipt; global authenticity is not inferred.

`inspect-reduction-job` returns `native_job_inspection_v1` with `job` and `dispatch`. The latter is `native_job_dispatch_observation_v1`, containing the derived nonce, actual matching original attempt ID, status and existing recovery report. No matching reservation is `no_reservation_observed`, an observation without execution/refund authority. The other states are exactly the four earlier recovery states. This operation creates nothing, executes nothing, reconciles nothing and changes no Job. It can expose committed research evidence while Catalog acknowledgment remains missing.

Valid state operations, including FAILED/LOST views, exit0; clients must inspect state. Validation is2, integrity/uncertain IO3, missing4, confirmation5 and Catalog ownership/version conflict9. A publication acknowledgment exception remains a nonzero unconfirmed error. `failure.worker_exit_code` is the actual observed child exit, including negative signals, or null if no worker started; diagnostic codes are not substituted for actual process exits. Reading a non-succeeded Job result remains conflict9. Native result bytes are the original canonical receipt without a trailing newline.

## Qualification and limits

Four remote installed profiles retain transcripts, actual path-free requests/IPC, PIDs and gates, raw Catalog/events/results, source/preparation/original ledger closures and exact file inventories under `native-jobs-*`. Core-only refuses unavailable/missing original evidence without claiming native success. Positive qualification freezes a separate explicitly synthetic **eight-slot** protocol before its baseline: source slots1–3, native results4–5, worker/coordinator faults6–7 and expired-publication admission8. There is no ninth slot. Historical five-slot execution, eleven-slot read-only Job lifecycle, golden and external handoff remain unchanged.

Required observations include actual native execution, original intent/CAS before launch, repeated submit/run without another slot, actual post-commit acknowledgment loss, worker/coordinator SIGKILL after native work at a recorded gate, stale credential refusal and expiry before research publication. Coordinator death is injected only after all preterminal heartbeats are durably observed, avoiding an unrelated hot-journal timing assumption. Native request/IPC sequences and raw nanosecond bytes must match actual persisted evidence. C-work alarm tests are distinct transport/OS fixtures, not additional research attempts.

Actual passing runs and scoped artifact audits are recorded in the implementation PR. Explicit idempotent retry, Job acknowledgment restoration and full checkpoint resume are not completed by this slice. CI/AI/owner are not external human reproduction; no new release, adoption, profit, full-history authentication or causal certification follows.
