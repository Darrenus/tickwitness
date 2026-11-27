# Corrected EC2 qualification v2 — 2026-11-27

Result: **NOT_QUALIFIED**. Run0003 reached18 PASS controls, then stopped after an
admitted UNKNOWN on control19 (`detached`); controls20–24 were not admitted.
Product M1 remains **DISABLED**, PR115 Draft and S13-02 / #38 incomplete. Human
security review remains NOT_PERFORMED and external-human reproduction0/0/PENDING.

## Actual source, execution and accounting

The source was `fae7fad81fe6107f0227fe70a9e9a3feeda52346`, fixed plan
`ec2-recovery-20261127-v2`, run `ec201aab11254e8bb7cd1573a96a0003`, original boot
`5fc1dec3-13e7-4d43-b584-314aedc95e6b`, service invocation
`00c83a6fcd104bde8d098c6b2c03ce36`. This implements the separately frozen
[v2 contract](../contracts/restricted-reference-ec2-recovery-v2.md) / ADR0049.
The source's remote Engineering run45863859414 passed all16 jobs and its separate
Documentation check passed. Source checks did not establish host qualification.

The owner started the existing selected instance at01:46:21 Asia/Singapore.
Pinned SSH identity, remote read-only history/preflight, lifecycle hashes/timer
and exclusive staging passed before one batch launch through the original
lifecycle wrapper. Trusted preparation and the ten-file source closure succeeded.
Control execution took about26.57s; the600s admission window was not exhausted.
The driver stopped on uncertainty and did not submit the remaining catalog.

| Actual observation | Retained result |
| --- | --- |
| Controls1–18 | PASS, with actual raw execution and independent observations |
| Control19, detached | Admitted UNKNOWN: `Missing separate host and guest namespace IDs` |
| Controls20–24 | Five unadmitted UNKNOWN; no later completion |
| Current charged / backend confirmed / payload starts | 19 / 19 / 19 |
| Historical charged / confirmed | 2 / 2, unchanged |
| Cumulative charged / confirmed | 21 / 21 |
| Pending outcomes / backend uncertainty | 0 / 0 |
| Manifest accounting | Original pre-probe current0 / cumulative2 |
| Final report accounting | Current19 / cumulative21 |
| Durable state | TERMINAL / NOT_QUALIFIED; poisoned=false |
| Successful final-report SHA / terminal receipt | null / null |
| Batch exit / history status | 1 / 0 |
| Research reservations / replay calls | 0 / 0 |

V2's one-use permission is consumed. Its unused five admissions are not a fresh
invocation allowance; no refund, reopening or automatic fourth window follows.
All three historical runs, clocks, source anchors and consumption records remain
unchanged. The original research protocol and common budget are unchanged.

## Control19 diagnosis and correction boundary

The assessor's `_detached_proof` applies `_namespace_ids`, which requires at least
two namespace IDs, to every observed before-kill cgroup member before selecting
the guest descendant. The first actual member is the host-side wrapper monitor
PID2646, whose valid `NSpid` and `NSsid` each contain only2646. That row raises the
exact reported exception before the actual guest descendant is considered.

The retained descendant PID2650 has `NSpid=2650 4`, `NSsid=2649 3`, matching
guest PID4/SID3, reserved UID61184, ignored SIGTERM and the same nonce. Its stopped
heartbeat retains389 ticks. The original deadline triggered exit-9;
stop_confirmed and cleanup_confirmed are true, the cgroup is empty/unpopulated,
the task is absent and protected canaries are unchanged. These facts identify a
member-classification defect; they do not retroactively change the recorded
UNKNOWN to PASS or establish the five unexecuted controls.

The narrow correction must distinguish valid host-only wrapper rows from the
guest candidate, preserving strict candidate uniqueness, PID/SID/UID, signal,
nonce, heartbeat and stop/cleanup checks. Remote regression must cover the actual
mixed four-member structure and malformed/missing or duplicate candidate rows.
The [next validation plan](ec2-reference-next-validation-plan.md) is prospective;
neither a source correction nor its tests grant another host invocation.

## Complete evidence retrieval and independently observed Stop

The original live journal SSH ended255 after916bytes/six lines, without archive
markers. Original qualification and consumption were correctly kept UNKNOWN
until existing disk evidence was retrieved. A later read-only retrieval boot
preserved the original138-byte lifecycle result before launching the unchanged
wrapper with only native `sleep300`. It ran no project, helper, exporter or claim.

Direct SSH readback recovered the existing archive:254026bytes, SHA256
`61049ada0e503279dc9f08b4109f82f64aa55d21d4fcf9cd950906a6d4e34064`,
with stable remote before/after stat and SHA. Full original-boot journal2497
records, unit32 and invocation27 were retrieved in bounded complete queries.
The original journal contains one matching BEGIN/END pair and21 base64 records;
independent decoding is byte-identical to the direct archive. No
EXPORT_UNCERTAIN marker exists. END precedes closure of the original reader's
SSH session by about168ms and ssh.service Stop by about198ms. This supports
shutdown interrupting live forwarding; missing reader/buffer/network evidence
prevents a more precise transport-cause claim.

The452 archive members /363 regular files were reviewed before inert extraction;
198 independently inventoried file hashes match archive members. All19 raw case
hashes/lengths and output pairs match the report and durable outcomes; tickets,
nonce, source/run/boot/manifest and original10s anchors agree. Ten source files
match the exact Git objects. Historical pins and before/after stat/hash records
are unchanged. The empty `export.stderr`, omitted by the original exporter, is
labelled inventory-confirmed-empty rather than fabricated inside the archive.

The failed report SHA256 is
`de0d9f217a6507a184715ee693c4a441587d9e7e38b954178dbf059da38d8117`;
manifest SHA256 is
`15af370090abf1bdbddc5576758afe40832b62155954d11f9b43fe56185ceb7d`.
The private readback audit seals412 files; its checksum-index SHA256 is
`bc394ad153734bc90ced8d4ceee33d08b50cfcc09af8039412f339a8dcfa8479`.
Raw private archives and earlier sealed evidence were not rewritten.

The exact retrieval boot/invocation/PID/sleep command were checked before guard
cancellation at18:14:13Z /02:14:13 Asia/Singapore. Fresh AWS control-plane refresh
then independently confirmed the same instance **Stopped**, no publicIPv4/DNS,
and `Client.InstanceInitiatedShutdown`. No agent cloud Start/Stop was issued.
The original batch's exit1 and the retrieval guard's lifecycle result remain
distinct. Retained EBS remains billable. AI cross-review is not human security
approval or an external-human reproduction attempt.
