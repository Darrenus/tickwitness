# ADR 0032: A coordinator owns durable comparison Jobs

Date: 2026-11-06 (Asia/Singapore). Status: implementation under review, S10-01.

S09 records immutable research attempts, but a coordinator or worker can die without a durable Job lifecycle. A missing research outcome must continue to mean consumed and unfinalized; adding Job orchestration cannot refund it or imply a completed research verdict.

The first supported operation is `compare_reduction_run_v1`. It invokes the existing pinned-source comparison in an installed, core-only worker and adds no research attempt. This provides a real vertical use case for QUEUED, RUNNING, SUCCEEDED, FAILED and LOST, with a separate one-attempt Job identity. Native research execution and retry are later integration work.

A trusted single coordinator owns an exclusive POSIX file lock and all SQLite writes. Workers receive a bounded, allowlisted JSON request and emit sequenced JSONL heartbeats or one terminal response. They receive no Catalog path, connection or descriptor. This separates trusted built-in capabilities; it does not sandbox hostile same-user code.

Every mutation checks the aggregate version, Job attempt, coordinator incarnation and lease token. Heartbeats are timestamped by the coordinator. Its current monotonic clock supervises delivery, while persisted UTC timestamps support diagnosis. Monotonic values never cross restarts. A read-only query exposes lost ownership, expired leases and backwards-clock uncertainty. A new exclusive coordinator may explicitly mark old-incarnation RUNNING records LOST. It never resumes or resets them.

Worker exit zero is insufficient for success. The coordinator independently reopens the source and live records and verifies the complete comparison export. A short SQLite transaction stores the result BLOB, terminal snapshot and event together. Commit errors remain visible and unconfirmed; they are never repaired by overwriting a possibly committed success with failure.

SQLite uses its local rollback journal so read-only readers need not create WAL/SHM files. Explicit writer ownership may invoke SQLite's normal journal recovery; read-only inspection does not repair a Catalog requiring recovery. This is separate from atomic research-manifest publication, application retry, complete engine checkpointing and backup/power-loss qualification.

Consequences: one writer and one active worker suffice for the first supported mode; submission can return a visible ownership conflict while a coordinator is active. No daemon, distributed queue, automatic retry, strong cancellation or hard total Job deadline is provided here. Heartbeats indicate message liveness, not research progress. A NOT_EVALUABLE comparison may be a successfully executed Job. External human reproduction remains 0 / PENDING, independently of software acceptance.

The worker limit applies to an active coordinator, not an instantaneous cross-incarnation OS-process cap. A read-only orphan stops when it observes a broken heartbeat channel; complete orphan reclamation and a measured cancellation bound remain S10-03 work.

The versioned interface and failure semantics are specified in [Job lifecycle v1](../contracts/job-lifecycle-v1.md). Remote installed evidence and owner acceptance are tracked in [Sprint 10](../planning/sprint-10-status.md) and [story #28](https://github.com/Darrenus/tickwitness/issues/28).
