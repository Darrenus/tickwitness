# One-use detached-member EC2 qualification v3

2026-11-27 Asia/Singapore. Reviewed fixed internal-reference contract. This contract and
[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md) must be reviewed,
committed, actually pushed and have the remote freeze revision read back before
implementation. The owner explicitly requested another actual AWS verification;
this is one new fixed technical allowance, not reopening
[v2](restricted-reference-ec2-recovery-v2.md) or treating source CI as host evidence.

Product M1 stays DISABLED, PR115 Draft and S13-02/#38 incomplete. Human security
review stays NOT_PERFORMED and external-human reproduction0/0/PENDING. AI review
is not either human gate. The original research protocol, common budget,
Job/family identities, committed-result verification/ACK rules, 5/8/11 fixtures,
golden and PR94 evidence remain unchanged. This qualification reserves zero
research slots and calls no replay engine.

## One fixed fourth qualification

Use only the same dedicated owner-selected EC2 instance, region, AMI, type and
x86_64 architecture fixed by [EC2 v1](restricted-reference-ec2-v1.md). No new VM,
credential, IAM grant, listener, GPU, arbitrary strategy or product mode is added.
Root owner, repository, provisioner, OS and runtime remain trusted; these records
do not attest against root.

The only new plan is `ec2-recovery-20261127-v3`; the only new run is
`ec201aab11254e8bb7cd1573a96a0004`. There is no arbitrary path/ID, plan generation
during claim, recursive successor, automatic fifth qualification or fallback.
A fresh source, nonce, boot or unused old admission grants no permission.

Use `ROOT=/var/lib/tickwitness-reference-ec2`. New fixed authority files are
`ROOT/recovery-v3/plan.json`, `ROOT/recovery-v3/consumption.json` and
`ROOT/recovery-v3/operator-stop.md`. Create with O_EXCL and fsync file and parent.
Existing or partial files are not replaced, renamed, chmodded or erased to gain
authority. Later phases read-only validate an exactly prepared plan/Stop file;
any existing consumption permanently fences another invocation. Old claims,
plans, consumption, sources, runs and operation/stage directories keep their
actual bytes and inodes, including v2's USED consumption and ceiling26.

## Fixed three-run history

Every new plan/context has exactly `history={original,recovery,recovery_v2}`,
not a caller-supplied or extensible history. `original` is exactly the twelve
fields and literal values inherited from v2's original entry; `recovery` is
exactly its eighteen fields and literal values. Their charged/backend_confirmed
remain1/1 each. Validate their old versions, source/boot/owner/anchors and lineage
without interpreting them under schema3 or a new historical total. The original
bounded root-owned host claim remains the same read-only global mutex.

`recovery_v2` has exactly the same eighteen field names as `recovery`, but
`case_sha256` is a fixed nineteen-key object instead of a scalar. Its literal
bindings, obtained from the sealed actual readback, are:

| Field | Fixed value |
| --- | --- |
| source_revision | `fae7fad81fe6107f0227fe70a9e9a3feeda52346` |
| run_id | `ec201aab11254e8bb7cd1573a96a0003` |
| boot_id | `5fc1dec3-13e7-4d43-b584-314aedc95e6b` |
| claim_sha256 | `c1bc4c14e01393567a254e9b8fe0c159021a2f9036eaa74bd388d3a9ad0e6d3c` |
| state_sha256 | `1b74bd77a9cb055f1cf567f0c6c2f6c5f9a44e28ad1d342ccd0aa4556f8b0236` |
| report_sha256 | `de0d9f217a6507a184715ee693c4a441587d9e7e38b954178dbf059da38d8117` |
| case_sha256 | Exactly the nineteen mappings below |
| source_lock_sha256 | `edb1a957feb47551c2a8b1ddce5d891e24e21d79d3c5ec6664088db6615a5d2d` |
| manifest_sha256 | `15af370090abf1bdbddc5576758afe40832b62155954d11f9b43fe56185ceb7d` |
| plan_sha256 | `de3288e8d1576684368256194e62d587a2ef52ddc7f0d542b043af8e6eafb43e` |
| consumption_sha256 | `e5b3e575fb4f23b7f0776997d50e43a74e9696232a27f5fe707bb25a738cd47b` |
| policy_setup_sha256 | `b6077d84db57d2678d75c44c0cf709d32df184eef64527b3ba558115e3f4df60` |
| policy_preload_sha256 | `02bfe910d218a4cbe6efb8ee63cd79993d61b996a541c71e867056737b01e9dd` |
| identity_document_sha256 | `c6427f9759c7e7a0a8e29cc4f2320eed55d62fba309aee86900b6ed36a072598` |
| archive_sha256 | `61049ada0e503279dc9f08b4109f82f64aa55d21d4fcf9cd950906a6d4e34064` |
| sealed_index_sha256 | `bc394ad153734bc90ced8d4ceee33d08b50cfcc09af8039412f339a8dcfa8479` |
| charged | Integer19 |
| backend_confirmed | Integer19 |

The exact `case_sha256` keyset and lowercase SHA256 values are:

| Key | SHA256 |
| --- | --- |
| case-01.json | `db855e1563a32f66b6cb62905696719501426cbb0d3418b57c4e0b885fc3a4e8` |
| case-02.json | `16204c395875e3b043cebf91bff2abf7a6a2a84c2c71bbb90d4c376b2b4cc4b0` |
| case-03.json | `4b7facc337d759ccf0a617655f8a536004452c239a68be0ed735369d19221eea` |
| case-04.json | `31f73b908adb03f1d91eb5eee14ccf44590c17a1d465a427ff7b8f1a571407ae` |
| case-05.json | `5e60aed174a3b7791678133ed0192deb41b2003e9d8f3fb6c15d9cb0ab7eb683` |
| case-06.json | `d7e6e02dc9d60ee92e239624e1e71a3fe92e743397282351b90819ca6ea5df84` |
| case-07.json | `3215c11deb98a9c85f16ed3fcaa5916ed883e458a91e28c5049fee9fcc927624` |
| case-08.json | `94ca893cf90f8920d092ef1db535cebca583b1e510a38cd62665e639320c740a` |
| case-09.json | `1085c7cfe5f8909965e0e5332c306a7f0e68295df01a2b648b819813cb2d1722` |
| case-10.json | `aef1b3e106ebef9fecb4568ac5995c7413958ef9ac5ed6132a5d2ef963f842aa` |
| case-11.json | `bf66c62aae4b210a81c43f85d595f6e583cdb13179ff12fbbaaeda29b2370ef9` |
| case-12.json | `2eeca5d0a7c0d40b6684aa0e6c18abae64e0a2e67afd9be8d3e13e27a1afc146` |
| case-13.json | `76845c80e71c6f0c6d96074bc729924c2b62da90358de5b63b78b8c070b5dac8` |
| case-14.json | `631d90aa20a82b46e10e10106f8821938ec05db32f0c1e42afa5037cfe407cd4` |
| case-15.json | `a408b13826636a2f2819571208cdeeb33ae5a9d2dd4a465829447bfd3df687b4` |
| case-16.json | `8c3a5204750a6592d38d7c23a148f2baac223e9f7ce7bb112c08a2c8ab47c4a0` |
| case-17.json | `33d13d41dd7158700115c5457df558908800eb3dbeb6a825b9b55740d8aa126b` |
| case-18.json | `eaca929b76ead6c0d9984f621632181a014ef92a8cece8630d6ef48e9e4d2d5f` |
| case-19.json | `b2c71d475b2090f7fb3a147201a78ba2dfa62ceb7c396bc911c392096e96c311` |

Read/seal actual bounded historical bytes using secure ancestry and no-follow,
nonblocking, root-owned single-link regular opens. Check stable inode/content
before and after preparation and claim. For all nineteen case files verify raw
size/SHA against the pinned report, the corresponding exact ticket/nonce,
source/run/boot/manifest/10s anchors and durable outcome. The third state remains
TERMINAL/NOT_QUALIFIED, reason `fixed_catalog_incomplete`, poisoned=false,
charged=confirmed=payload_starts19, pending/ACK uncertainty0, successful final SHA
and receipt null. Its report retains18 PASS, case19 admitted UNKNOWN and five
unadmitted UNKNOWN. Its manifest remains pre-probe current0/cumulative2; final
report remains current19/cumulative21. Do not rerun the corrected assessor on
these old bytes to change the historical verdict or require poisoned=true as in
the first two setup refusals.

Preserve actual producer encoding: historical identity documents are raw bounded
strict JSON, not forced canonical; historical preload records use their original
canonical encoding without trailing LF. Other authority records retain their
own original canonical-LF encoding. Archive/private index digests are retained
transport provenance, not a claim to rehash private files absent on the host.
No project instance, `_live` or receipt call is made for an old boot during
history verification; such a call could mutate old terminal state.

Copy only the exact1222-byte owner Stop observation to the new Stop path, SHA256
`85cf2e0aea083bae7cfacbe6f52c3c2b49c5bcc057b73fed3c7f3491b9be8f07`.
It records independently refreshed AWS Stopped/no publicIPv4/DNS and
Client.InstanceInitiatedShutdown after the read-only retrieval boot
`5e83ad22-d623-4ddd-87f8-41a27a599f2d`, not a fourth qualification. It grants no
technical admission and is trusted owner evidence, not signed AWS attestation.
Preserve the old858-byte and2322-byte Stop files unchanged. The new qualification
boot must differ from all three historical qualification boots and this
retrieval boot.

## Explicit schema3 and actual budget21

Keep default, recovery-v1 and recovery-v2 paths, kinds, schemas and refusal
behavior unchanged. Add only explicit
`Ec2Run.claim_recovery_v3(source_revision,run_id,plan_id)` returning the exact
Ec2Run type. The CLI accepts exactly the three frozen plan literals and dispatches
explicitly; unknown IDs/versions, abbreviations, arbitrary paths, subclasses and
fallback are refused.

All new qualification authority kinds are `restricted_reference_ec2_recovery_`
plus plan, consumption, context, run, claim, host, source_lock, manifest,
qualification, terminal_receipt or budget, with suffix `_v3` and exact integer
schema_version3. Shared policy/preload/raw-case envelopes retain their existing
versions with strict embedded schema3 authority. Reject duplicate, unknown or
missing fields, bool-as-int, oversized/noncanonical authority and unstable file
identity. Independently retained canonical authority is never reconstructed from
mutable state or inferred from a non-null context.

The v3 plan has exactly the same twelve keys as v2: kind, schema_version, plan_id,
freeze_revision, source_revision, run_id, expected_identity, history, allowance,
stop_observation, source_lock and provisioner_source. The Stop observation keeps
its four v2 keys and owner-observation kind/state/reason, binding the new fixed
file. Implementation pins the actual pushed/read-back freeze commit; the caller
cannot choose that revision. Its allowance has exactly:

| Field | Value |
| --- | --- |
| additional_invocations | 1 |
| max_admissions | 24 |
| window_ns | 600000000000 |
| setup_ns | 30000000000 |
| max_cumulative_admissions | 45 |

Source provisioning adds explicit `--recovery-v3 <source40>`. Its source lock has
the five v2 keys, new kind/schema3, and exactly the original nine qualification
source files plus `scripts/prepare_ec2_reference_recovery_v3.py`. The helper
verifies all history, Stop, current source closure and new boot, holds the
original read-only host-claim flock during validation/exclusive plan publication,
and rechecks its original descriptor/path and every sealed file. It opens no
qualification clock, metadata request, policy or probe, and never imports old
helpers. The separately reviewed operational packet binds exact Git objects/SHA
for `scripts/provision_ec2_reference_source.sh`,
`scripts/run_ec2_reference_recovery_v3.sh` and
`scripts/ec2_reference_handoff_v3.py`; these three are not extra source-lock
entries. Stage files and actual operation copies must match those objects.

At factory entry capture started/deadline/setup anchors once, before history,
source, plan, IMDS, runner or policy validation. Validation consumes the original
600s/30s clocks; constructing another object cannot renew them. Under the original
read-only host-claim LOCK_EX|LOCK_NB, validate all immutable records and exclusively
create/fsync v3 consumption and parent before any new run, metadata or policy.
The consumption has the same exact sixteen v2 keys; history_state_sha256 has
exactly original/recovery/recovery_v2 state digests, prior_charged21 and caps24/45.
Its source/boot/owner/freeze/plan/original anchors must match. Verify complete
expected bytes and retain the seal from the same read. Existing/partial/uncertain
consumption is permanently used, including failure before a first probe.

The context keeps the exact eight v2 keys, with the fixed three-entry history.
Keep public recovery_context/recovery_accounting/recovery_accounting_phase.
Plan/consumption/context/claim/provider/policy/setup/preload/manifest/report/
receipt and live calls must agree byte-for-byte on immutable authority and seals.
Do not leak CLOEXEC descriptors to guests or let a caller FD/state edit change
source, history, allowance, owner or anchors.

Accounting keeps exactly the fourteen v2 budget keys. Its historical_run_ids is
the ordered list [run0001,run0002,run0003], using the complete literal IDs above;
prior_charged=prior_backend_confirmed21, max_current_admissions24 and
max_cumulative_admissions45. Current counters come from the actual live snapshot;
cumulative counters are21 plus the corresponding current counter. Schema3 is a
wire version, not the historical charge. No formula substitutes version3 or the
number of history entries for21. On uncertain persistence remove authoritative
current/cumulative counts and retain explicitly labelled confirmed lower bounds;
UNKNOWN never becomes zero, a refund or permission to resubmit.

Keep all original per-task controls: deadline min(original600s deadline,
admitted+10s), separate2s stop confirmation, CPU25000/100000 fair-class bandwidth,
memory256MiB/swap0/oom.group1, pids32,16MiB/512inode tmpfs, FD64/file8MiB,
CORE0/RTPRIO0,64KiB per stream, required namespaces/seccomp/NNP/zero retained
capabilities and supplementary groups, independent bootstrap/guest labels,
immutable input/canaries and exact-owned cleanup. No unload, isolation fallback,
global relaxation, force/lazy cleanup or result reuse. Raw process-limit text/PID
remains available on observer refusal; GO/payload_started stay behind all gates.
The corrected detached assessor identifies exactly the four independently bound
live roles; no arbitrary host row is skipped.

## Complete new acceptance

The manifest has the same exact41 keys as v2, with new kind/schema/context and
immutable pre-probe current0/cumulative21. Validate its full shape, phase, version
and authority before the first submission. All24 original controls must pass on
this one new source/run/boot/manifest, with actual24 charged=confirmed/payload
starts, cumulative45, no poison/pending/ACK uncertainty and confirmed stop/cleanup.
Every ticket/nonce/outcome must match actual raw case bytes/report references and
unchanged canaries. Old PASS results cannot fill the new catalog. Any early
failure or uncertainty stops new submissions, retains real consumed counts and
leaves the remaining controls unadmitted.

Fsync the complete report, record its actual successful SHA in durable TERMINAL
state, and independently re-read matching state/report and successful terminal
receipt in the same original live boot. Persist the actual receipt bytes before
handoff, as part of retained qualification stdout or an exclusive receipt file.
A later read-only retrieval performs inert byte/hash/JSON association checks;
it never reclaims or calls the old live authority. Report, state and successful
receipt retain the same actual final24/cumulative45 snapshot. Qualification and
evidence transport have separate outcomes: lost SSH, failed export, bad download
or late ACK cannot rewrite an already committed report or its original exit.
Without complete evidence local acceptance remains UNKNOWN, never inferred pass.

## One bounded controller and original automatic Stop

Keep the original verified lifecycle launcher, wrapper, Stop hook and active
enabled four-hour boot timer unchanged, with private umask077. Use a new root0700
stage `/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3`, scripts0500 and
Stop0400. Remote syntax, secure ancestry, exact source hashes, current access and
no active same-name test session are checked before the sole launch. Source
preparation/tests do not start an instance. A reviewed concrete package and fresh
complete remote checks for its actual implementation source are required before
the established account/access/Start procedure. Prior f7 source success is not
qualification of a later v3 implementation.

The thin batch shell execs the root-owned1500s+2s timeout and the stdlib helper's
`run` operation; one Python master owns the actual Controller state machine.
It survives SSH loss under the original lifecycle service. Its real phase,
single-export and internal handoff methods use narrow injectable ports for
remote regression; no public test-mode or separate test-only state machine is
introduced. Capture one operation monotonic outer start/deadline at launch. Before
trusted preparation, atomically create and fsync the new fixed operation
directory
`/var/lib/tickwitness-lifecycle/reference-batches/ec201aab11254e8bb7cd1573a96a0004`
(OPERATION). Any existing/partial operation permanently refuses a second
controller, even when qualification consumption was never created. No overlapping
wrapper, alternate operation path, operation reset or pre-claim restart is allowed.

All operational authority files have fixed names directly under OPERATION:
controller-start.json, qualifier-exit.json, export-call.json,
export-consumption.json, handoff-ready.json, handoff-ack.json,
controller-cancel.json and controller-result.json. The only pending/final archive
names are archive.pending and evidence.tar.gz. No caller chooses these paths.

| Phase | Fixed host ceiling; no new admission allowance |
| --- | --- |
| Entire controller | 1500s, then at most2s TERM/KILL confirmation |
| Trusted preparation | 480s, then at most2s termination |
| Qualifier process | 612s, then at most2s termination |
| Actual qualification admission | Original600s; original30s setup inside it |
| Qualifier's extra12s host margin | Existing2s stop confirmation plus at most10s report/receipt-only finalization; no probe or renewed clock |
| Single export | 25s, then at most2s termination; archive at most16MiB |
| Handoff/ACK | At most120s from one original handoff start |

Each phase deadline is min(phaseStart+its cap, operationOuterStart+1500s);
termination grace cannot go past the outer2s grace. A shortened remaining phase
does not renew any internal clock. Trusted preparation precedes factory anchors;
the612s qualifier watchdog includes process startup and never extends its actual
600s admission window. Original3h50min wrapper and90s Stop timeout/four-hour timer
remain independent upper safeguards. Stop/receipt-only margin authorizes no new
probe, reservation or replay, and unconfirmed termination never becomes success.

Exclusively publish/fsync `controller-start.json` with exactly ten keys: kind,
schema_version, source_revision, run_id, boot_id, controller_pid,
controller_start_ticks, controller_argv, started_ns and outer_deadline_ns. Its
kind is `restricted_reference_ec2_controller_start_v3`, schema_version integer3;
outer_deadline_ns=started_ns+1500000000000. The PID/start ticks and bounded actual
procfs argv bind this live Python master and its reviewed exact `run` command.

Invoke the qualifier at most once and exporter at most once. Exclusively publish
and fsync `qualifier-exit.json` with exactly eight keys: kind, schema_version,
source_revision, run_id, boot_id, invoked, returncode and report. Its kind is
`restricted_reference_ec2_qualifier_exit_v3`, schema_version integer3. invoked is
a strict boolean meaning the sole launch attempt was initiated: set it true
before Popen, and never change it back after spawn failure or unknown exit.
returncode is the actual integer code or null when not observed; null is not0.
report is an actual fixed-path record with exactly path/bytes/sha256 or null
when it could not be preserved. A partial/malformed report can be retained as
raw bytes without claiming it valid; null does not prove absence. Preserve this
exit record before export/handoff decisions. Do not synthesize, overwrite or
reopen the qualification report/state/receipt.

Preserve preparation, qualification, export, handoff and controller statuses
separately. Only successful export, valid ACK, qualifier invoked=true and an
observed integer qualifier returncode in0..255 allow the original qualifier code
to be returned. A missing invocation, unknown/null or negative original code,
any phase timeout or export/handoff failure/expiry returns74 while original
qualifier-exit remains immutable. Do not pass a signed negative child code to
sys.exit and mistake its modulo256 OS status for that original code.
Preparation failure before a qualifier launch retains invoked=false and null
returncode, without inventing a qualifier exit; preserve its actual preparation
return code separately.
No cleanup path invokes the qualifier/exporter twice. Any internal export entry
point is restricted to this fixed live operation and a one-use exclusive export
fence; it cannot serve as a standalone re-export or retrieval command.

Before the sole exporter launch, the master exclusively creates/fsyncs
`export-call.json`. Its internal-export child must prove that its actual parent
is the same live master, with the original start ticks/argv and actual guard
cgroup. Before archive creation that child exclusively creates/fsyncs
`export-consumption.json`. Each has exactly eight keys: kind, schema_version,
source_revision, run_id, boot_id, controller_pid, controller_start_ticks and
started_ns. Their respective kinds are `restricted_reference_ec2_export_call_v3`
and `restricted_reference_ec2_export_consumption_v3`, both schema_version
integer3. They bind the same start-record master/source/run/boot; started_ns is
the corresponding actual one-time call/consumption observation, not a new export
deadline. The original parent-started25s ceiling still covers the entire child.
Any existing/partial call or consumption permanently prevents another exporter.
The child then creates `archive.pending` exclusively, fsyncs its complete bytes
and publishes `evidence.tar.gz` without replacing an existing target, then fsyncs
the parent. Final archive must be a stable single-link regular file. Partial
pending/final bytes are retained, not removed to obtain a second export.

After export/handoff, attempt once within the remaining outer deadline to
exclusively publish/fsync `controller-result.json`. It has exactly thirteen keys:
kind, schema_version, source_revision, run_id, boot_id, preparation_invoked,
preparation_returncode, qualifier_invoked, qualifier_returncode, export_invoked,
export_returncode, handoff_status and returncode. Its kind is
`restricted_reference_ec2_controller_result_v3`, schema_version integer3.
Each invoked flag is a strict boolean meaning the unique launch attempt was
initiated, set before Popen and kept true after an uncertain submission/result.
Each corresponding phase returncode is the actual signed integer or null;
invoked=false requires null, null never becomes0 and bool is not an integer code.
qualifier_invoked/qualifier_returncode must exactly match qualifier-exit.json.
handoff_status is exactly one of not_started, acknowledged, expired, cancelled,
failed or unknown. The external returncode is in0..255 and follows the preceding
original-code-or74 rule; this result cannot rewrite any phase result. It is
created after the single export/handoff attempt and preserved independently, not
claimed to be inside a previously published archive. A failed export may leave
no complete archive. Missing/partial final result stays uncertain and grants no
publication retry or clock extension.

Export bounded actual operation scripts/logs, plan/consumption/Stop/source lock,
all new raw cases/outputs/tickets/outcomes/manifest/report/receipt and all three
complete historical source/run/plan/consumption/Stop anchors. Verify history
before/after stable hashes and metadata. Publish one exclusive stable archive
with original byte count/SHA. Missing auxiliary records are explicitly absent
or inventory-only, never fabricated as archived bytes. Retain bounded journal
markers as corroboration; direct archive transfer is the independent return
channel. Neither logging nor collection extends a qualification deadline.

## Fixed independent-download acknowledgement

Use only the root-owned stdlib `scripts/ec2_reference_handoff_v3.py` from the
reviewed packet. Its public execution/download operations are:

```text
run --source-revision SOURCE40 --run-id ec201aab11254e8bb7cd1573a96a0004
ack --source-revision SOURCE40 --run-id ec201aab11254e8bb7cd1573a96a0004 \
    --boot-id BOOT --invocation-id INVOCATION --main-pid MAINPID \
    --controller-pid CONTROLLERPID --nonce NONCE --bytes BYTES --sha256 SHA256
cancel --source-revision SOURCE40 --run-id ec201aab11254e8bb7cd1573a96a0004 \
    --boot-id BOOT --invocation-id INVOCATION --main-pid MAINPID \
    --controller-pid CONTROLLERPID
```

The master calls its wait method internally without exec or a public wait mode;
reconstructing a waiter cannot restart a handoff anchor. No caller-selected unit,
path, deadline or test-mode is exposed. The only service
is `tickwitness-test-session.service`. Ready has exactly these twenty-two keys:
kind, schema_version, source_revision, run_id, boot_id, unit, invocation_id,
main_pid, main_start_ticks, main_argv, guard_exec_start, guard_control_group,
controller_pid, controller_start_ticks, controller_argv, nonce, bytes, sha256,
archive_stat, started_ns, deadline_ns and outer_deadline_ns. Its kind is
`restricted_reference_ec2_handoff_ready_v3`, schema_version integer3.
archive_stat has exactly nine keys: device, inode, mode, uid, gid, nlink, size,
mtime_ns and ctime_ns. Size must equal bytes and remain in1..16MiB; root ownership,
single link, regular no-follow identity and before/after seal/SHA are mandatory.

ACK has exactly eleven keys: kind, schema_version, source_revision, run_id,
boot_id, invocation_id, main_pid, controller_pid, nonce, bytes and sha256. Its
kind is `restricted_reference_ec2_handoff_ack_v3`, schema_version integer3.
Every operational JSON record is at most65536 bytes. All shapes use strict
bounded canonical JSON, reject duplicate/unknown/missing
fields and non-JSON numeric constants, and require secure root-only ancestry and
single-link no-follow regular files. PID/tick/byte/time integers reject bool;
source/run/boot/invocation/SHA identities and argv strings are bounded. The nonce
is exactly32 lowercase hexadecimal characters, freshly generated once using
token_hex(16), never caller-selected for ready construction.

Ready binds the actual current service InvocationID/MainPID, both process start
ticks, exact guard/controller commands and new source/run/boot. main_argv and
controller_argv are bounded actual NUL-delimited procfs argv converted to string
lists; each must match its reviewed fixed launch command. guard_exec_start is
the actual systemctl string, and guard_control_group is its actual cgroup.
ControllerPID means the original still-live Python master recorded at controller
start, not a presumed Bash parent, MainPID or an arbitrary root process. The same
master enters handoff and proves its PID/start ticks/argv and membership in the
guard's actual ControlGroup. ACK independently checks that exact master and the
active/running guard invocation. ACK/cancel processes from independent SSH need
not belong to the unit cgroup: check the live master/guard membership, not the
caller's. Only the internal exporter must be the master's same-cgroup child.
MainPID and controllerPID retain their separate
actual identities even when a particular launch gives them equal values.

Capture started_ns once at wait entry; deadline_ns is
min(started_ns+120000000000, outer_deadline_ns). The outer deadline comes from the
validated exclusive controller-start record, never a caller argument or a new
clock. Complete ready publication/validation consumes this same handoff window.

An independent SSH connection first downloads the existing archive, captures
stable before/after remote stat/SHA and verifies local original bytes/count/hash
and safe inert archive contents. It also preserves actual ready bytes/stat/SHA
and their exact archive binding. Only then send ACK for that observed ready
identity. ACK publication requires the same live boot, unit invocation, MainPID,
controllerPID/start ticks/commands and nonce, unchanged archive bytes/seal and
source/run/length/SHA, with server time still inside the original120s and outer
deadline. Recheck after bounded verification and before O_EXCL publication;
fsync ACK and parent. It is trusted owner download acknowledgement, not signed
proof of local review or a successful qualification.

The archive is published before ready: controller-start, qualifier-exit,
export-call/consumption and before/after history records belong in its single
export; ready contains its SHA and therefore remains outside it. ACK and later
handoff/controller observations are also outside that old archive, never falsely
claimed to have been inside it. Retain actual later bytes independently when
available; the later result uses only its exact thirteen-key shape. Missing ACK
command stdout after normal Stop stays UNKNOWN, not permission to resend ACK, re-export
or requalify. The downloaded qualification archive and its committed report are
not rewritten because a later operational reply is missing.

Stale/wrong/malformed/late ACK produces zero protocol writes and cannot stop or
renew the waiter. The waiter continues only its original deadline; ACK absence
or uncertainty ends with transport74 and automatic Stop. Existing/partial ACK is
never overwritten or used to create another admission. Valid ACK lets the
controller exit with the retained original qualifier code, so the unchanged
lifecycle hook owns Stop.

Cancel works during preparation/qualification before ready exists: read the
existing controller-start record and validate the supplied source/run/boot/unit
invocation/MainPID/controllerPID against the complete current guard/master
identities, procfs start ticks, reviewed exact commands and actual cgroup. A
wrong/stale/malformed identity produces zero protocol writes or signals. A valid
request exclusively creates/fsyncs `controller-cancel.json` with exactly ten
keys: kind, schema_version, source_revision, run_id, boot_id, invocation_id,
main_pid, controller_pid, controller_start_ticks and requested_ns. Its kind is
`restricted_reference_ec2_controller_cancel_v3`, schema_version integer3;
requested_ns is the actual live monotonic request observation, not a new clock.
Reconfirm that same guard identity before cancelling the original unit and
letting its unchanged lifecycle hook own Stop. Never signal a stale or recovered
PID. An existing/partial cancel, failed fsync or missing command reply is retained
and never overwritten or automatically resent. Cancellation admits no second
qualifier/export and does not certify Stop until actual confirmation.

At success, failure, disconnect, cancellation, export failure, invalid/missing ACK
or any deadline, retain available committed/partial evidence and stop through the
original lifecycle. Independently refresh AWS to observe the same instance
Stopped/no publicIPv4/DNS; SSH exit/disconnect or a Stop request is insufficient.
If transport is incomplete, preserve partial local bytes and disk evidence and
review a separately bounded read-only retrieval; never renew a guard, resubmit,
rerun the exporter or infer a free allowance. Retained EBS remains billable.

Before an actual Start, remote source/driver/history/budget/manifest regressions
and controller/handoff regressions must cover successful and failed qualifiers,
claim/preparation failure, original exit preservation, single export failure,
disconnect during execution/download, partial/bad-SHA/missing archive, wrong or
stale identity/ACK, duplicate/partial ACK, clock exhaustion during verification,
each phase timeout, cancellation and independent Stop observation boundaries.
Every path proves no second qualifier/export/admission, fixed clocks, intact
history and honest uncertainty. Passing those tests still does not qualify AWS.
Full actual24-control reference success still does not enable M1, supply human
review/reproduction, merge/release the PR or authorize a fifth qualification.
