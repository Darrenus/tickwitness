# One-use dedicated EC2 recovery qualification v1

2026-11-26 Asia/Singapore. This is the explicit new reviewed plan required by
[EC2 v1](restricted-reference-ec2-v1.md) after the
[first failed qualification](../security/ec2-reference-evidence-2026-11-25.md).
This contract and [ADR0048](../adr/0048-one-use-ec2-recovery-qualification.md)
must be independently reviewed, committed, actually pushed and the remote ref
read back **before recovery implementation or another host qualification**.
It authorizes one additional bounded **technical** qualification invocation;
it does not reopen or refund the original invocation or any research budget.

M1 product remains **DISABLED**, PR115 remains Draft and #38 incomplete.
Independent human security review remains NOT_PERFORMED and external-human
research reproduction0/0/PENDING. A source test or this plan is not a host pass.
S13 capacity and original protocol/Job/family identities,5/8/11 fixtures, golden,
PR94 and committed-result verification/ACK rules remain unchanged.

## Fixed scope and predecessor

Only the same owner-selected EC2 instance, region, AMI, instance type and
architecture from EC2 v1 are allowed. No replacement VM, credential, IAM rule,
network listener, GPU, arbitrary-source execution or SDK/CLI product mode is
introduced. The root owner, trusted provisioner, clean repository and OS remain
trusted; these records are not tamper-proof evidence against that owner/kernel.

The fixed plan ID is `ec2-recovery-20261126-v1`; its sole successor run ID is
`ec201aab11254e8bb7cd1573a96a0002`. There is no arbitrary plan path, alternate
plan ID, automatic plan generation during a claim, recursive recovery chain or
third invocation. The predecessor is exactly:

| Binding | Immutable expected value |
| --- | --- |
| Source | `ae3d8e7981a79d6fc692f2cb656534a2f9a6683b` |
| Run | `ec201aab11254e8bb7cd1573a96a0001` |
| Boot | `122c5232-f007-4fe1-b555-6797ee475eba` |
| Host claim and run claim SHA256 | `7406dfdd9e66a47a2e19761d9501891258f839d4dbefc5b2089b8876780fafca` |
| Terminal state SHA256 | `2b4b455b60f97d5052ae4bcb81c01f41566708a9c9486a94de71dee03eb13a5d` |
| Failed report SHA256 | `dcb7b4a585b9b02601f21697d2bb2c06bc5f480bc5a04e205e38d79c3abb1152` |
| First case SHA256 | `dd5fb4e40f9b88fb2926808fb7a3e82f6720a356ea196dc5cebbfa8eb0a1450b` |
| Source lock SHA256 | `ed9f02ac04541945ceaab9021836984aa6e12c9fc9bad4be9308b5602e564d5c` |
| Retained private archive SHA256 | `4203ef17dff24fe38cd2107e93a1b764e8bfacc96e87172251dfe5630f48aba5` |
| Owner-recorded AWS Stop observation SHA256 | `a64c30e2fff9fad194184ee278636e19da6ebfecbcae1f19ffe715b2db266193` |

Verify actual bounded predecessor claim/state/report/case/source-lock bytes and
their cross-bindings. Its state is TERMINAL/NOT_QUALIFIED, poisoned=true,
charged1/backend_confirmed1, exactly one accepted positive admission with a
non-null outcome, stop_confirmed=true and cleanup_confirmed=true. Pending
outcomes and unconfirmed backend admissions are0. Its successful final-report
hash and successful terminal receipt are null as expected for that failed path.
Its fixed positive result is setup_refused, payload_started=false, and its
remaining23 cases are unadmitted UNKNOWN. A pending/unknown outcome or resource
is a refusal, not evidence that cleanup may be assumed.

The historical AWS Stop record is a **trusted owner observation**, not signed
AWS attestation or a new live cloud query. Preserve its exact bytes at the fixed
root-owned path `ROOT/recovery-evidence/operator-stop.md`, where
`ROOT=/var/lib/tickwitness-reference-ec2`. Bind it by the digest above and an
actual byte count. Its recorded state/reason are Stopped and
Client.InstanceInitiatedShutdown. The retained archive digest identifies the
previously verified private transport archive; it does not claim that runtime
re-hashes an archive that was not transferred back to the host.

All historical host/run/source records and their inodes/bytes remain untouched.
Do not rename, delete, rewrite or chmod the old fixed host claim to admit this
successor. Reboot must produce an actual boot ID different from the predecessor;
old monotonic times are never translated, resumed or reissued.

## Explicit additional technical allowance

The predecessor's one charged admission stays charged. Its original600s window
and30s setup remain ended. The successor receives **one newly reviewed**600s
window and30s setup, with at most24 submissions from the complete fixed catalog.
This is a separate declared technical allowance, not a reset of the first one.
Capture both new anchors exactly once at recovery factory entry, **before**
predecessor/source/plan validation, IMDS, policy or runner construction. Validation
time consumes those same new deadlines. Recreated objects cannot renew them.

Report historical1 + current actual charged count, maximum25 across these two
invocations. Historical confirmed1 is also retained; current pending outcomes
and ACK uncertainty remain separate. A complete success requires all24 cases
on the one new source/manifest, with current charged=confirmed=24 and cumulative
charged=confirmed=25. The old failure cannot be reused as a positive pass; the
unsubmitted23 cannot be combined with a different source or boot to qualify.

All per-task controls stay as in EC2 v1: original10s admission including setup,
separate2s confirmed-stop bound, CPU25000/100000 fair-class bandwidth,
memory256MiB/swap0/oom.group1, pids32, one16MiB/512inode tmpfs, FD64/file8MiB,
CORE0/RTPRIO0,64KiB per stream, required namespaces, NNP, zero retained effective
capabilities, immutable input/canaries and exact-owned cleanup. No research
reservation or replay-engine call is authorized by this technical allowance.

## Secure preparation and source closure

Preparation runs only on the selected remote CPU host through the already
verified lifecycle wrapper. Keep its private umask077 and active/enabled4h
boot timer. Only fresh owned input directories receive explicit0755; the
[permission correction](../security/ec2-reference-evidence-2026-11-25.md) does
not widen global controls or reopen the failed run.

The provisioner preserves its default one-source-argument behavior and the exact
old nine-file source-lock kind. Its explicit `--recovery <source40>` form selects
`restricted_reference_ec2_recovery_source_lock_v1`, schema1, the same nine files
plus `scripts/prepare_ec2_reference_recovery.py` as the tenth exact entry. The
new lock is exclusively created under the new source revision; no existing lock
is rewritten. The actual pushed implementation revision must include the input
correction and recovery implementation and pass its remote source checks.

The new trusted preparation helper verifies that source lock and the preserved
predecessor/Stop bytes before exclusively writing `ROOT/recovery-plan.json`.
Default v1 never reads that file as permission. Preparation itself opens no
qualification window, policy load or hostile probe. Full repository/preparation
and transitive runtime remain owner-trusted; ten hashes do not authenticate every
import or prove independent review. The implementation pins this actual freeze
commit after its push/readback; an arbitrary caller-supplied review string cannot
select a different plan or predecessor.

## Strict records and one-use consumption

All new records use schema_version exactly integer1, canonical JSON, bounded
root-owned regular single-link files with secure non-symlink ancestry. Reject
duplicates, unknown/missing fields, bool-as-int counters, malformed digests,
oversized files, changed identity/content and unsupported kinds. File records
have exactly `{path,sha256,bytes}`, actual bounded bytes and fixed allowed paths.
Plan and consumption are at most65536B; state/report remain262144B and raw case
results2097152B. Regular-file opens use NOFOLLOW/NONBLOCK and stable read checks.

The plan kind is `restricted_reference_ec2_recovery_plan_v1`; exact keys:

```text
kind schema_version plan_id freeze_revision source_revision run_id
expected_identity predecessor allowance stop_observation source_lock provisioner_source
```

`expected_identity` is the exact EC2 v1 five-field selection. The exact predecessor
keys are `source_revision,run_id,boot_id,host_claim_sha256,claim_sha256,state_sha256,
report_sha256,case_sha256,source_lock_sha256,archive_sha256,charged,backend_confirmed`,
with the literal bindings above and both counters1. `allowance` has exactly
`additional_invocations=1,max_admissions=24,window_ns=600000000000,
setup_ns=30000000000,max_cumulative_admissions=25`. `stop_observation` has exactly
`kind=trusted_owner_aws_stop_observation_v1,observed_state=Stopped,
reason=Client.InstanceInitiatedShutdown,evidence=<fixed file record>`.
`source_lock` binds the actual new ten-file lock; `provisioner_source` binds the
actual tenth helper source. Source revision and successor run must match the
selected actual invocation, not a branch label.

`Ec2Run.claim_recovery(source_revision,run_id,plan_id)` returns the same exact
Ec2Run type, preserving loader/backend exact-type guards. The default `claim()`
continues exclusively creating the fixed original host claim and refusing reuse.
Recovery instead opens that existing fixed host claim **read-only**, verifies its
original bytes/inode and holds LOCK_EX|LOCK_NB for the entire live invocation.
The old claim is the shared host mutex, not the new run's own claim. Live checks
independently verify both identities and every sealed predecessor/plan/source
record; recovery cannot compare the new claim bytes against the historical file.
This mutex is scoped to the selected local EBS filesystem, not network-filesystem
locking or protection against malicious root. Lock/plan descriptors are CLOEXEC
and never passed into the guest; no caller-supplied inherited FD is authority.

After validation under that lock and before creating a successor run, accessing
metadata or adding policy, exclusively create **global**
`ROOT/recovery-consumption.json`. Its kind is
`restricted_reference_ec2_recovery_consumption_v1`; exact keys:

```text
kind schema_version plan_id plan_sha256 freeze_revision source_revision run_id
boot_id owner started_ns deadline_ns setup_deadline_ns predecessor_state_sha256
prior_charged max_admissions max_cumulative_admissions
```

The owner is the actual PID/start-ticks/UID plus invocation identity. It binds the
already captured new anchors, prior_charged1 and caps24/25. Persist bytes and
fsync the file and parent **before** proceeding. This is the sole global extra
invocation consumption, not a caller-selected per-plan path. Existing, partial,
empty or uncertain consumption permanently refuses another automatic attempt.
An exception after exclusive creation never erases/refunds the record, even if
no payload or new run was created. A validation refusal before consumption grants
no window; elapsed anchors are never reused to retry within that invocation.

New run/claim kinds are `restricted_reference_ec2_recovery_run_v1` and
`restricted_reference_ec2_recovery_claim_v1`, schema1, original strict fields plus
`recovery_context`. New provider kind is
`restricted_reference_ec2_recovery_host_v1`, schema1, the original14 exact fields
plus `recovery_context`; provider family stays `aws_ec2_dedicated_v1`.
The context kind is `restricted_reference_ec2_recovery_context_v1`, schema1,
with exactly `kind,schema_version,plan_id,plan,predecessor,consumption,invocation,
allowance`. Plan/consumption are exact file records; predecessor/allowance equal
the plan; invocation contains exactly `source_revision,run_id,boot_id,started_ns,
deadline_ns,setup_deadline_ns` and matches the live claim and consumption.
Capture its canonical immutable bytes independently of mutable run state. Live
claim/state/provider context must match those original bytes and sealed plan/
consumption; modifying state and calling persist cannot redefine lineage,
allowance, source or anchors.

Policy/preload EC2 v1 outer kinds may remain: they already embed the complete
versioned provider context and require exact equality across preload, loader,
setup, manifest and live run. Foreign opaque attachments retain UNKNOWN; no
profile is unloaded, replaced, silently reused or placed in autoload directories.
Fresh current-name absence and the one fixed add, independent bootstrap **and**
guest labels and all original controls must be observed again on the new boot.

## Reports, uncertainty and final gates

The explicit driver selector is `--recovery-plan ec2-recovery-20261126-v1`;
no arbitrary path/abbreviation or fallback to default claim on failure. New
manifest/report/terminal kinds are respectively
`restricted_reference_ec2_recovery_manifest_v1`,
`restricted_reference_ec2_recovery_qualification_v1` and
`restricted_reference_ec2_recovery_terminal_receipt_v1`, schema1. Default v1
record shapes and refusal behavior stay unchanged.

Expose `run.recovery_context` (null for default) and
`run.recovery_accounting(snapshot)` (null for default, exact live snapshot
required). The accounting kind is `restricted_reference_ec2_recovery_budget_v1`,
schema1, with exactly `kind,schema_version,plan_id,predecessor_run_id,prior_charged,
prior_backend_confirmed,current_charged,current_backend_confirmed,
current_unconfirmed,current_pending_outcomes,cumulative_charged,
cumulative_backend_confirmed,max_current_admissions,max_cumulative_admissions`.
These are actual durable current counts plus the fixed historical1; caps24/25.

The immutable context is identical across claim/state/provider, policy records,
manifest, report and terminal receipt. The immutable manifest carries its actual
pre-probe accounting snapshot, current0/cumulative1, labelled by its construction
phase; it is never rewritten to the final count. Driver admission checks require
that initial kind/context/provider/snapshot before the first probe. Report
accounting advances with actual durable admissions. Successful final report and
terminal receipt carry identical final current24/cumulative25 accounting; do not
require the initial manifest's counts to equal the terminal snapshot.

Recovery final validation also binds each same-source/run/boot admission ticket
and nonce to its durable outcome and actual case file bytes/SHA256 under that
run directory. A case name/PASS string alone cannot import an older result.
Before a recovery factory returns actual authority, a refusal report may name the
explicit recovery kind but omits unestablished context and authoritative counters;
it must not invent a consumed plan or a zero-charge success.

Snapshot or persistence uncertainty removes current authoritative cumulative
values as well as current per-run counters; retain any prior confirmed values
only as explicitly labelled lower bounds. Missing/unknown evidence never becomes
an authoritative zero, free retry or fresh allowance.

Keep the original success protocol: fsynced complete report, durable TERMINAL
record containing its actual SHA256, and a re-read matching terminal receipt.
Recovery success additionally requires exact recovery report/provider/context/
accounting bindings and all24 current same-source PASS cases, with no pending,
ACK uncertainty, poison or missing stop/cleanup. A v1-looking report that drops
lineage, omits the historical charge, changes source/plan or mixes old results
cannot qualify. Failed or uncertain publication retains consumption and records.

The existing lifecycle wrapper must export bounded evidence and request Stop at
completion/failure/cancellation. Independently observe AWS Stopped afterwards;
SSH loss or a request alone is insufficient. The operator starts the existing
instance only after source checks and the concrete execution package are ready.
Even a full exact-tuple pass is only QUALIFIED_REFERENCE_ONLY; product M1,
independent-security and external-human gates remain separate and closed/pending.
