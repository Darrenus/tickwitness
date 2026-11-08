# Explicit native Job retry and acknowledgment v1

S10-02c implementation under review, 2026-11-08 (Asia/Singapore). Owner merged [PR103](https://github.com/Darrenus/tickwitness/pull/103), accepting S10-02b at `a521abba087d747b306ed1271188a3a5a4da58e4`. [Story29](https://github.com/Darrenus/tickwitness/issues/29) remains open pending this slice's owner acceptance. External humans **0 / PENDING**.

## Identity and immutable history

`reduction_followup_job_spec_v1` adds operation `resolve_reduction_job_v1` without changing the five-field Job envelope, SQLite schema1, existing comparison/native descriptors, one Job attempt or immutable terminal states. Request fields are exactly `origin_spec`, `parent_job_id`, `mode`, `idempotency_key`. The origin is the full original `reduction_execution_job_spec_v1`, embedded once without recursive ancestors. Mode is `retry_from_origin_v1` or `acknowledge_committed_v1`; key is1–128 ASCII letters/digits/period/underscore/hyphen, starting alphanumeric. Lease is inherited exactly from the origin; locator, input, engine, split, checkpoint and budget overrides are unavailable.

Identity is SHA-256 of the complete canonical descriptor. Idempotency is scoped to parent, mode and key. Same descriptor returns the same Job; changed keys represent explicit requests. Catalog submission atomically validates the actual terminal parent and complete original ancestry, and permits at most one retry successor per parent. Other-key retry siblings conflict; acknowledgment records do not occupy that retry successor. An acknowledgment-only Job cannot become a native parent. Chains have at most32 original/retry dispatches. Parent and origin must exist in the same Catalog at admission; orphan RUNNING must first be explicitly reconciled to LOST. Neither retry nor recovery rewrites an old FAILED/LOST/SUCCEEDED record.

## Original-ledger lineage and execution

Current native coordinators share a nonblocking POSIX family lock under the already-existing original ledger, at `.job-followups/ORIGIN_JOB_ID`. Metadata contains the exact immutable `origin.json`, an empty `coordinator.lock`, and immutable parent-ID-to-child-spec claims. Paths use no-follow bounded reads, same-user ownership checks, no-replace publication and directory synchronization. Actual original source/preparation/prefix is verified before metadata creation. The journal is not a replacement ledger, slot, research intent or outcome, and grants no budget. A broken or conflicting journal fails closed; a claim without confirmed slot/Catalog publication does not authorize free replay.

Every current original native or retry coordinator holds the same family lock through original-slot admission, native execution, independent audit, research publication and Job completion. A busy family fails visibly before research admission. An immutable retry claim is committed before its new original reservation. This serializes current cooperating coordinators across Catalogs and stale backups; a different successor cannot bypass the claim. Quiesce pre-upgrade coordinators before using this protocol. Same-user trusted storage remains the boundary, without hostile-code containment, global history authentication or cross-store atomicity.

Before retry, the coordinator independently reads every registered dispatch's actual original reservation/intent/CAS/outcome using its Job-derived nonce. Any verified committed receipt or failure leads only to acknowledgment. Otherwise retry claims the current leaf and consumes a new actual slot under the unchanged original protocol, binds the exact preparation and starts the existing native worker from the frozen origin. An already consumed child nonce with no outcome cannot execute again. No slot is imported, returned, reset or reused. Native wall time, renewable Job lease, current owner/OCC/token checks and result reconstruction retain the [native execution contract](native-reduction-jobs-v1.md).

## Read-only research recovery and separate acknowledgment

Acknowledgment mode reads family metadata without creating locks, directories or claims. It independently verifies an existing original terminal via [attempt recovery](reduction-attempt-recovery-v1.md), including committed failures and full receipt/state-audit closure. It performs no native/runtime availability check, subprocess, reservation, intent binding or research publication. No observed terminal produces a clear non-success result; missing evidence is not certified global absence. A committed descendant may be recovered from the durable journal even if a stale Catalog lacks that descendant row.

The new result is an exact `reduction_job_resolution_v1` with fields `kind`, `schema_version`, `job_id`, `origin_job_id`, `parent_job_id`, `action`, `dispatch_job_id`, `outcome`. Action is `replayed_from_origin` or `acknowledged_committed`. Outcome is the original verified `reduction_run_receipt_v1` or `reduction_attempt_failure_v1`, preserving its own meaning. Actual dispatch nonce binds the dispatch Job, not an acknowledgment Job. Replay action requires the current retry Job and a run receipt. A structurally valid wrapper alone does not authenticate the original ledger; independent verification precedes completion.

The current coordinator checks ownership, version, credentials and UTC/monotonic lease, including after blocking Catalog reads, then atomically commits wrapper BLOB, new Job terminal and event through existing `complete`. The original terminal remains unchanged. An error after actual Catalog completion is unconfirmed error3; repeating the same descriptor reads persisted SUCCEEDED without an event, research write or execution. A lost acknowledgment Job requires a new explicit recovery key. There is no transaction across the family journal, original file ledger and SQLite, no physical real-time fsync guarantee and no automatic retry.

## CLI and qualification

```sh
tickwitness retry-reduction-job PARENT_JOB_ID --retry-key retry-1 --jobs /owner/jobs
tickwitness run-job NEW_JOB_ID --jobs /owner/jobs
tickwitness recover-reduction-job PARENT_JOB_ID --recovery-key acknowledgment-1 --jobs /owner/jobs
tickwitness run-job ACK_JOB_ID --jobs /owner/jobs
tickwitness read-job-result ACK_JOB_ID --jobs /owner/jobs
```

Submission queues only; confirmation is denied before identifiers/Catalog IO. Existing result readers return unchanged original payloads; followup result readers return the new wrapper. Catalog-only native/research facts for followups remain unknown rather than asserting that acknowledgment replayed an engine. Read-only `inspect-reduction-job` returns a separate resolution observation for followups, with the registered dispatches and actual verified committed outcome; legacy inspection shape is unchanged.

Remote installed qualification freezes a distinct, explicitly titled synthetic **five-slot** protocol before baseline: source1–3, native worker failure4, explicit native retry5 with actual research commit/ACK loss. At exhaustion, core-only acknowledgment, its own coordinator death/stale credentials and post-Catalog-commit response loss must consume no slot6 or native execution. Duplicate keys, siblings, cross-Catalog lock contention, stale Catalog recovery, original terminal immutability and exact raw Catalog/research/IPC closure are separately checked. Historical five-slot, eight-slot, eleven-slot, golden and PR94 evidence remain independent; no frozen budget is increased. Actual current CI and artifact audit evidence is published in the implementation PR, never predeclared passing.

Explicit retry/acknowledgment do not implement complete checkpoints, strong cancellation, total-resource policy, full orphan/temp reclamation, release, external human approval, market adoption or profit. Those limits remain visible; S10-03 is planned separately.
