# One-use corrected EC2 qualification v2

2026-11-27 Asia/Singapore. The owner explicitly requested a real AWS verification
of the corrected source after the [second failed host attempt](../security/ec2-reference-recovery-evidence-2026-11-26.md).
This is a new, separately bounded technical allowance. It does not reopen
[recovery v1](restricted-reference-ec2-recovery-v1.md), erase either failed charge,
or make source CI a host qualification. This contract and
[ADR0049](../adr/0049-one-use-corrected-ec2-qualification.md) must receive independent
static review, be committed and actually pushed, and have their remote revision
read back before v2 implementation or another host qualification.

Product M1 remains DISABLED, PR115 Draft and #38 incomplete. Human security review
remains NOT_PERFORMED and external-human reproduction 0/0/PENDING. AI review is
not independent human security acceptance. The original research protocol,
Job/family identities, budgets, 5/8/11 fixtures, golden, PR94 and committed-result
verification/ACK rules remain unchanged. This technical qualification reserves
no research slot and calls no replay engine.

## Exactly one new selection

Only the same dedicated owner-selected EC2 instance, region, AMI, instance type
and x86_64 architecture fixed by [EC2 v1](restricted-reference-ec2-v1.md) are allowed.
No new VM, credential, IAM grant, listener, GPU, arbitrary strategy or product
execution mode is introduced. The root owner, provisioner, full repository, OS
and transitive runtime remain trusted; these records do not attest against root.

The only new plan is `ec2-recovery-20261127-v2`, and the only new run is
`ec201aab11254e8bb7cd1573a96a0003`. There is no caller-selected path or plan ID,
plan generation during claim, recursive recovery chain, automatic fourth
invocation or fallback to v1.
The v1 plan, consumption, both old runs and source locks retain their actual
bytes and inodes. A corrected source, reboot, changed nonce or unused old case
does not grant this allowance without this distinct fixed v2 path.

Use `ROOT=/var/lib/tickwitness-reference-ec2`. New fixed files are
`ROOT/recovery-v2/plan.json`, `ROOT/recovery-v2/consumption.json` and
`ROOT/recovery-v2/operator-stop.md`. All creates use O_EXCL: existing or partial
files are never replaced, renamed, chmodded or erased to obtain authority.
Later phases read-only validate the exactly prepared plan and Stop file;
any existing consumption permanently fences another invocation.

## Fixed two-run history

Every plan and context contains exactly `history={original,recovery}`. This is
a fixed two-member object, not an extensible list or a user-supplied history.
`original` has exactly the twelve predecessor fields and literal values frozen
by recovery v1, including run `ec201aab11254e8bb7cd1573a96a0001`, source
`ae3d8e7981a79d6fc692f2cb656534a2f9a6683b`, boot
`122c5232-f007-4fe1-b555-6797ee475eba`, charged1/backend_confirmed1 and all original
claim/state/report/case/source-lock/archive hashes. The original host claim is
still the unchanged bounded root-owned file and global mutex.

`recovery` has exactly these eighteen fields, with charged and backend_confirmed
both integer1. The remaining sixteen literal bindings are:

| Field | Fixed value |
| --- | --- |
| source_revision | `d5f5fab9978d0cb2d1fed92f32552632705d52ee` |
| run_id | `ec201aab11254e8bb7cd1573a96a0002` |
| boot_id | `503b0e3e-0efe-4d7c-99b3-e282176c4c29` |
| claim_sha256 | `e1f4a1e805ce62b3d5758ac4c372101b34c4e5945f5629864352c80aa5825b42` |
| state_sha256 | `bb59f7c5027f3d61b5cefd0a8674ffb1e9fc7514cebc5bcc1aa6e14a62a3d1a5` |
| report_sha256 | `ca3048f10484f0bd8c8f1aa7c30db5e672f922fff799ec6b83f7659569b8d5fc` |
| case_sha256 | `572844853e49d00720682332d89a718ee5e424a63252c47998010a37a448cf4a` |
| source_lock_sha256 | `a878a9eaf805559cce4358aa678f7e5b99dea8ea9d31bc9d5af8246155836bf2` |
| manifest_sha256 | `261bd6890d6c064949fa7960916079f72e65316cbfe367472fab57a968a137be` |
| plan_sha256 | `c10d872d2eb24fd7dc2ab6fc655222a6de44ecbe4742a26d1c113f4f9daf47f9` |
| consumption_sha256 | `1df9fc47bb1b66ee0f67fa64edb3086a156b6faca749b3a4b3647abd59c4b5e1` |
| policy_setup_sha256 | `2fe0bddd7b8d09998ecf7ae758ee7385603e0d063cf6d75e4ddf6a85bc0eb4f8` |
| policy_preload_sha256 | `b0f57477e2a85abd090a8688a0ecd680e20a424ea46bc5d6d2462f473e6e7798` |
| identity_document_sha256 | `8a01b4cb7de9b5fe1c376abe3fd0479942219b3dd3eb485acbd82991adc1b831` |
| archive_sha256 | `4ade0f15fd75a2ac6e457f798ec55e72880bbffad602d72ded3c9c3b427f692f` |
| sealed_index_sha256 | `6516ceb56fbc302484cf391cc0c0434a3414c5e6ad6cb33ccbed06a9b1323571` |

Read and seal the actual bounded historical bytes, with secure ancestry,
NOFOLLOW/NONBLOCK regular single-link opens and stable inode/content checks.
Verify the old recovery plan/consumption/context still bind the original run,
the actual second source/boot/owner/anchors and its original v1 allowance. Both
old states are poisoned TERMINAL/NOT_QUALIFIED with charged=confirmed=1, one
accepted positive admission and a durable setup_refused outcome, confirmed
stop/cleanup, zero pending or ACK-unknown admissions, and null successful final
hash/receipt. Bind each actual case SHA/size and ticket/nonce to its own durable
outcome and report. The second manifest remains its pre-probe current0/cumulative1;
its failed final report remains current1/cumulative2. Never reinterpret those
old records using the new schema or new prior count.

The archive and private checksum-index digests are retained transport provenance,
not a claim that runtime rehashes private files not present on the host. The
second attempt's raw process-limit readback was not retained; the exact failed
row and whether the repaired formatting defect was the sole cause remain UNKNOWN.
READY did not establish GO, positive probe-body execution or a passed resource limit.

Copy only the exact 858-byte owner control-plane Stop observation to the new
operator-stop path: SHA256
`b6fbd33d2d0c8f9f0da20f31535a13d058785665ee9fc0d70baa4116517f7d6d`.
It records Stopped and Client.InstanceInitiatedShutdown after run0002. It is
trusted owner evidence, not signed AWS attestation or a current cloud query;
its earlier evaluation-phase wording is preserved. The original 2322-byte v1
Stop file and its binding remain unchanged.

## New allowance and original controls

Exactly one newly reviewed invocation has at most24 submissions from the complete
fixed catalog, one600s window and30s setup. Capture both anchors once at factory
entry before historical/source/plan validation, IMDS or runner/policy construction.
Validation consumes those deadlines; reconstructing objects cannot renew them.
Historical charged=confirmed=2 stays charged. Maximum cumulative charged or
confirmed is26, and a full success requires current24/confirmed24 plus history2.
Old results or remaining23-case subsets cannot qualify a new source/boot.

Keep all EC2 v1 per-task limits: original10s including setup, separate2s confirmed
stop, CPU25000/100000 fair-class bandwidth, memory256MiB/swap0/oom.group1, pids32,
one16MiB/512inode tmpfs, FD64/file8MiB, CORE0/RTPRIO0,64KiB per stream, required
namespaces/seccomp/NNP/zero retained capabilities and supplementary groups,
independent bootstrap and guest labels, immutable input/canaries and exact-owned
cleanup. No policy unload, optional-isolation fallback, global-control relaxation
or force/lazy cleanup. Preserve raw process-limit text/PID on observer refusal;
complete observation, payload_started and GO remain behind all independent gates.

## Separate strict v2 authority

Keep default claim() and recovery-v1 behavior, kinds, schema1 and paths unchanged.
Add only explicit `Ec2Run.claim_recovery_v2(source_revision,run_id,plan_id)` returning
the same exact Ec2Run type. The driver `--recovery-plan` accepts only the two fixed
literal IDs and dispatches explicitly to the matching factory. Unknown versions,
paths, abbreviations, arbitrary IDs or failure fallback are refused.

New source provisioning has a distinct explicit `--recovery-v2 <source40>` mode.
Its lock is `restricted_reference_ec2_recovery_source_lock_v2`, schema_version2,
with exactly the original nine source files plus
`scripts/prepare_ec2_reference_recovery_v2.py` as its tenth entry. V2 does not
execute/import the old preparation helper. The helper validates both historical
slots, exact current source closure and Stop bytes and exclusively publishes the
fixed new plan, under the same read-only host-claim flock; preparation opens no
qualification clock, policy, metadata request or probe. Implementation pins the
actual pushed/read-back freeze commit, never a caller-supplied review string.
Only a pushed reviewed implementation containing the corrected observer and
passing remote source checks may be staged for the actual host batch.

All new v2 authority kinds use schema_version exactly integer2 and the suffix
`_v2`: recovery_plan, recovery_consumption, recovery_context, recovery_run,
recovery_claim, recovery_host, recovery_source_lock, recovery_manifest,
recovery_qualification, recovery_terminal_receipt and recovery_budget, each
prefixed `restricted_reference_ec2_`. Exact keys, canonical bounded JSON, duplicate
and unknown/missing-field refusal, bool-as-int refusal, stable root-owned single
link records and secure ancestry remain mandatory. Shared policy/preload/raw-case
envelopes keep their existing versions; their embedded provider/context must bind
the exact established v2 authority, never be accepted by non-null inference.

The v2 plan has the same twelve top-level keys as v1 except `history` replaces
`predecessor`. Its allowance has exactly additional_invocations1,max_admissions24,
window_ns600000000000,setup_ns30000000000,max_cumulative_admissions26.
Stop-observation keys/kind/state/reason remain as v1 but bind the new fixed file.
Source-lock/provisioner-source records bind the actual v2 source and helper.

Hold LOCK_EX|LOCK_NB on the original host-admission.json opened read-only for the
entire live invocation. Its inode and bytes are not a new claim. Under that lock,
recheck actual host identity, both history slots, fixed plan, current source and
boot different from both historical boots. Exclusively create and fsync the new
global v2 consumption and its parent before creating a new run, metadata or policy.
The consumption has the sixteen v1 keys except `history_state_sha256` replaces
`predecessor_state_sha256`; this is exactly an object with original/recovery
state digests. prior_charged is2; caps24/26. Its remaining owner/plan/source/boot/
freeze/original-anchor fields have the same exact semantics as v1. Existing,
partial or uncertain consumption is permanently used; never refund it on error.

The context has the eight v1 keys with history replacing predecessor. Public
record fields remain recovery_context/recovery_accounting/recovery_accounting_phase.
Keep immutable canonical authority independent of mutable state. Run/claim/provider,
policy/setup/preload, manifest/report/receipt and live calls must match its exact
original bytes and all sealed records/inodes. No caller FD or persisted state edit
can alter source, history, allowance, owner or anchors. Descriptors stay CLOEXEC
and never enter the guest. Exact-type loader/backend guards remain.

V2 accounting has the fourteen v1 budget keys except `historical_run_ids` replaces
`predecessor_run_id`; its exact ordered list is [run0001,run0002]. Prior charged
and confirmed are2, and max_current/max_cumulative are24/26. The same actual-live
snapshot and ticket/outcome validation apply. Snapshot/persistence uncertainty
removes current authoritative current and cumulative counts, preserving only
explicitly labelled confirmed lower bounds; UNKNOWN never becomes zero or a refund.

## Complete acceptance and automatic shutdown

Manifest has the same exact41 keys as recovery v1 with the new kind/schema/context.
Its immutable pre-probe accounting is current0/cumulative2. Before the first probe,
the driver must reject unknown/missing keys, wrong phase/version/context/counts.
Final success requires all24 current same-source/run/boot/manifest PASS controls,
current24/cumulative26, no pending/ACK uncertainty/poison, each durable admission
ticket/nonce/outcome matching actual raw bytes and report reference, and confirmed
stop/cleanup with unchanged canaries. The old manifest is never overwritten or
required to equal a final snapshot. Fsync the complete report, record its actual
SHA in durable TERMINAL state, and independently re-read the matching successful
terminal receipt before publishing QUALIFIED_REFERENCE_ONLY. Any incomplete,
failed or uncertain evidence remains NOT_QUALIFIED and retains all charges.

Use only the existing verified lifecycle supervisor, private umask077 and active,
enabled original4h boot timer. Stage a fresh root0700
`/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v2` with scripts0500 and Stop0400;
verify source hashes, safe ownership/ancestry, remote shell syntax and no active
test session. Do not rewrite old stage/operation directories. Independently start
the journal reader before the sole batch launch. Preserve the exact current
batch/preparer, operation logs, new source/run/plan/consumption/Stop, both complete
historical run/source anchors and old plan/consumption/Stop in a bounded export.
Retain25s+2s transport,16MiB bound and run-bound archive markers/SHA/byte count;
transport limits grant no probe or renewed clock. Missing export remains UNKNOWN.

Only start the existing instance after the concrete reviewed source package and
source checks are ready, respecting the established account/access/manual Start
requirements. At completion, failure or cancellation the lifecycle supervisor
owns automatic Stop. Independently observe AWS Stopped afterwards; SSH loss or a
request is insufficient. Retained EBS remains billed. Even an exact reference pass
does not enable product M1, perform human security review, complete external-human
reproduction, merge/release the PR, or authorize a fourth host window.
