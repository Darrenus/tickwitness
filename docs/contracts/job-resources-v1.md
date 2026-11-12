# Job resources v1

Frozen before S11-01 implementation,2026-11-12 Asia/Singapore. Owner merged [PR105](https://github.com/Darrenus/tickwitness/pull/105) at `8f2f27880f1753bd754ec7220fbac3045d143905`, accepting S10. Story31 retains11h within S11's33h and ongoing quality capacity; these are estimates, not actual time. External humans remain0/PENDING.

## Authority and compatibility

Newly executed Jobs with an existing frozen control policy collect a separate operational report. Old/unconfigured Jobs are not retroactively measured. Store immutable bounded canonical bytes at `.job-resources/JOB/report.json`, outside the strict control journal. Preserve every existing Job descriptor, schema1, control result, research receipt and terminal rule. Resources are observations, never authority to execute, reserve, refund or reset a research budget, or evidence that a research claim is true. Upgrade with older coordinators quiescent.

Inspection reads without creating directories, reconciling Jobs, executing native code or reconstructing input research. Missing reports return NOT_RECORDED and unknown, including coordinator death before publication; seals, old PIDs, UTC differences and current host counters cannot reconstruct old usage. Existing reports bind their actual collected snapshot; inspection separately reports the current snapshot digest and whether it still matches after explicit reconciliation. Malformed or conflicting reports fail visibly rather than becoming unknown.

## Strict report

`job_resource_report_v1`, schema_version1 has exactly: kind, schema_version, job_id, job_attempt_id, policy_id, catalog_state, catalog_snapshot_sha256, worker_started, worker_usage, collection_status, metrics, stages. Job/attempt/policy/snapshot identifiers are lowercase SHA256; attempt/state/snapshot can be null only when not observed. No lease tokens, nonce, arbitrary paths or free-form strategy data. Canonical bytes are limited to16KiB. Report ID is SHA256 of the complete canonical document. Integers are nonnegative signed64, booleans/floats are forbidden in metric values. Identity/state/raw-snapshot binding is verified by the application and storage adapters.

Each metric has exactly availability,value,unit,scope,source,reason. availability is measured or unavailable. Measured values are integers with reason=null; unavailable values are null with a fixed reason. Metric name fixes unit/scope/source; unsupported measurements never silently become0. Exact names:

| Metric | Unit | Scope | Source |
| --- | --- | --- | --- |
| coordinator_cpu_ns | ns | coordinator_process | process_time_ns_delta |
| compute_user_cpu_ns | ns | terminated_compute_child_os_accounting | anchor_wait4 |
| compute_system_cpu_ns | ns | terminated_compute_child_os_accounting | anchor_wait4 |
| compute_peak_rss_bytes | bytes | terminated_compute_child_os_accounting | anchor_wait4 |
| scratch_cleanup_logical_bytes | bytes | owned_scratch_cleanup_regular_entries | nofollow_cleanup_stat |
| job_elapsed_ns | ns | live_control_window | monotonic_ns_delta |
| research_slots_reserved_count | count | this_job_confirmed_new_reservations | coordinator_reservation_confirmation |
| audited_native_results_count | count | this_job_new_native_results_audited | coordinator_native_result_audit |
| processed_input_record_count | count | this_job_audited_native_result | coordinator_native_result_audit |
| predicate_evaluation_count | count | frozen_research_predicate | not_instrumented |

Reasons: not_recorded, worker_not_started, usage_unavailable, unsupported_platform, cleanup_incomplete, reservation_unconfirmed, result_not_audited, not_instrumented, phase_not_observed, clock_unavailable. Predicate evaluations are unavailable/not_instrumented in this version: replay calls, records, heartbeat messages and outcomes are not predicate evaluations. Reservation count starts at known0, becomes unknown before a potentially committing authorization, and becomes1 only after an actual reservation confirms. Audited-result count records coordinator observations, not unobserved engine activity. Processed records become known only after independent actual native-result audit; other cases stay unknown.

collection_status complete means applicable operational collection finished with a terminal snapshot and supported worker/cleanup observations, not that all optional capabilities or research evaluation exist. Partial collection remains a valid report, independent of SUCCEEDED/FAILED/LOST. A worker that was never started has unavailable worker usage with reason worker_not_started, never a fabricated measured memory0. An orphan without a report stays NOT_RECORDED.

## Owned OS accounting and time

Trusted stdlib session anchor uses wait4 only for its current owned compute child on normal and stop paths. A separate anonymous nonblocking pipe carries one canonical newline JSON frame of at most512 bytes, no more than actual PIPE_BUF. Only anchor retains its writer; compute branch explicitly closes it before exec, coordinator closes its writer after Popen. Coordinator drains a bounded amount after its existing wait; no EOF wait, extra kill/reap or business IPC changes. Missing/truncated/oversized/duplicate/invalid frames make usage unavailable. Resource collection cannot weaken existing stop, group absence or lifetime rules.

Raw worker_usage is null or the exact frame: kind=job_compute_usage_v1,schema_version1,anchor_pid,compute_pid,platform,user_cpu_us,system_cpu_us,maxrss_raw,maxrss_unit,compute_wait_status. PIDs bind the actual unreaped anchor and its distinct compute child. platform is linux or darwin; RSS raw unit KiB for Linux, bytes for Darwin, converted explicitly to bytes. CPU is rounded to nearest microsecond, then represented as multiples of1000ns; the ns unit does not imply nanosecond CPU precision. Kernel accounting may include OS-defined waited descendant usage; it is not complete process-tree sum or simultaneous memory peak. Do not use global RUSAGE_CHILDREN differences. Anchor's deadline exit and compute wait status can differ; usage never rewrites the original exit or cause. Unsupported hosts produce unknown usage.

All stages use one coordinator's live monotonic offsets, bounded by job_elapsed_ns. The stages field is a list of exactly four items in this order: pre_worker_admission,owned_worker_lifetime,cleanup,post_cleanup. Each has exactly name,availability,start_offset_ns,end_offset_ns,duration_ns,reason. Measured duration=end-start and0<=start<=end<=elapsed; missing endpoints are null/phase_not_observed. Worker lifetime includes bootstrap, IPC, holds and stopping, not pure native compute. Total starts before claim/preparation; excludes waiting for Catalog ownership and report persistence. No wall-time/UTC reconstruction across restarts. Not every failure completes every stage; stages do not promise exhaustive coverage or summation to total.

Disk counting reuses the existing bounded no-follow cleanup traversal after confirmed stop/free lifetime lock. Sum logical sizes of successfully unlinked regular-file entries; hard links count per directory entry, symlinks are not followed or counted. Full successful cleanup makes this a complete observation; incomplete cleanup is unavailable, with original diagnostics and retained scratch. When this coordinator never created a workspace, it knows there were no owned scratch entries and records0; this does not invent worker memory or CPU0. No extra pre-cleanup recursive scan, new grace or weakened bounds. This is not peak scratch, physical bytes freed, unique CAS bytes or aggregate storage enforcement. Reference-aware garbage collection belongs to S11-02.

Report publication is once, no-replace and fsynced. A report write failure is an explicit operational IO diagnostic; committed research/Job/control results are never overwritten or rolled back, and no implicit report retry or new execution occurs. Existing managed-write accounting still charges report bytes where applicable. Telemetry is not a distributed/authenticated billing system.

## Metadata-only preview

`preview-job-resources JOB --jobs PATH --split development` reads only the existing Catalog descriptor and optional control policy. `inspect-job-resources` additionally reads this immutable report. Confirmation is rejected before ID, filesystem or Catalog IO. Neither command creates metadata, holds coordinator ownership, reconciles, reads source/normalized research data, opens confirmation evidence, invokes an evaluator/native engine or reserves/publishes anything.

Preview is a strict `job_resource_preview_v1` document with kind,schema_version,job_id,operation,policy_id,configured_limits,estimates,research_slot_requirement,execution_authorized. execution_authorized=false. configured_limits are the existing frozen policy limits or null, never estimated usage. estimates have exactly cpu_ns,peak_rss_bytes,elapsed_ns,disk_bytes, each unavailable/null/reason=not_calibrated; there is no calibrated prediction in v1. research_slot_requirement has availability,value,reason: measured0/structurally_read_only for comparison or explicit acknowledge_committed_v1; unavailable/null/conditional_execution for native/retry, which may instead confirm an existing result. Never promise globally available remaining slots from an observed prefix. Preview does not reveal bearer credentials or raw descriptor paths.

## Qualification

Keep17 checks and the existing four controls profiles/timeouts. Explicit optional resource qualification reuses their existing original8-slot lifecycle, queue cancellation, transport/orphan and post-exhaustion ACK; it adds no native call/slot9 or larger budget. Preserve old5/8/11,golden and PR94. Archive separate resource qualification report, actual raw usage, immutable reports, metadata previews, exact before/after directory hashes and original accounting. Qualification must verify compute PID/provenance/units, real CPU/RSS, actual resource-file cleanup bytes, partial/missing/unsupported/tampered observations, confirmation denial and read-only preview. No machine-specific performance threshold, GPU, release, adoption or external-human claim.

## Reading cost observations

```sh
# Before execution, after submitting a Job and optionally freezing its controls:
tickwitness preview-job-resources JOB_ID --jobs /owner/jobs
# After the existing run-job workflow finishes:
tickwitness inspect-job-resources JOB_ID --jobs /owner/jobs
```

Inspection returns job_resource_inspection_v1 with job_id,policy_id,current_snapshot_sha256,report_id,report,report_matches_current_snapshot,status and execution_authorized=false, plus schema_version1. Status is RECORDED for complete collection, PARTIAL for partial collection, or NOT_RECORDED when no report exists. Missing report and its identity/match are null. A recorded snapshot must belong to the actual Catalog history; explicit later reconciliation may change the current digest while retaining the valid original observation. There is no resource-result repair command, old-PID resampling or hidden execution behind inspection.

An unknown prediction is expected without calibration. A configured60 CPU seconds is an enforcement ceiling, not an estimate of60 CPU seconds of work. A partial report may accompany a committed successful result; a complete operational collection may accompany a cancelled Job. Read the existing Job/control/research records for their separate outcomes.

References: [Python wait4](https://docs.python.org/3/library/os.html#os.wait4), [Linux resource accounting](https://man7.org/linux/man-pages/man2/getrusage.2.html), [Apple kernel resource manual](https://github.com/apple/darwin-xnu/blob/main/bsd/man/man2/getrusage.2).
