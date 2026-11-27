# One-use EC2 v3 execution and evidence return

This is the operator flow for the reviewed
[v3 contract](../contracts/restricted-reference-ec2-recovery-v3.md) /
[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md), frozen in actual
pushed/read-back commit `72c83a02d47a403d5f9d33aad2f84ccaba7ec6a4` before
implementation. It is one fixed fourth qualification, not a reusable runner.
This document is an operation guide, not a claim that the host has passed.

The plan is `ec2-recovery-20261127-v3`; the run is
`ec201aab11254e8bb7cd1573a96a0004`. Retain historical charged/confirmed21 from
run0001/run0002/run0003. This invocation permits at most24 new fixed controls,
with cumulative ceiling45. Original research budgets, protocol/Job/family
identities and committed-result ACK behavior are unchanged. No research slot or
replay engine is used by these synthetic host controls.

## Complete the source package before Start

Record the selected actual implementation SOURCE40 and Git tree. Require fresh
complete remote Engineering16/16 and Documentation success for that source,
actual CI checkout tree equality, and retained raw logs and artifact identities.
The earlier f7 classifier repair is a baseline; it does not qualify later v3
implementation. Keep the separate legacy GHA policy refusal as a refusal.

Review the production Controller, historical bindings, budget/manifest/driver
tests and actual subprocess/handoff negative regressions. Tests must include
phase expiry, unknown launch/exit, single export, partial/missing/bad-SHA
archive, malformed/stale/wrong ACK, pre-ready cancellation, PID reuse, fsync
failure, SSH loss and an independent supervisor handling controller death.
Passing those tests is source evidence, not actual24-control host evidence.

Prepare an immutable private deployment packet from actual selected Git objects:

- `scripts/provision_ec2_reference_source.sh`;
- `scripts/run_ec2_reference_recovery_v3.sh`;
- `scripts/ec2_reference_handoff_v3.py`;
- the exact1222-byte owner Stop observation, SHA256
  `85cf2e0aea083bae7cfacbe6f52c3c2b49c5bcc057b73fed3c7f3491b9be8f07`.

Record each packet byte count/hash, selected source/freeze/tree, current source
checks and all historical pins. The operational scripts are separately bound;
the qualification source lock remains exactly the original nine files plus
`scripts/prepare_ec2_reference_recovery_v3.py`. Never use an old v2 batch packet.

## Access and read-only preflight

Use only the existing instance `i-0d79530ca78320939`, account `010057564982`,
region `ap-southeast-1`, instance type `m7i.2xlarge` and AMI
`ami-09289bc217ad5e9e7`. Verify the actual account/instance before any Start.
Follow the established access and manual-Start procedure; do not work around
an approval rejection through another API or CloudShell. Do not create a new
instance, credential, IAM grant or wider ingress rule. Start only when the
reviewed source package is ready, so the host is not waiting for development.

After Running, obtain the current publicIPv4 rather than a historical address.
Use the existing dedicated SSH key only through the client. Verify the original
ED25519 fingerprint before authentication:
`SHA256:zB2adSrLIJ6RbqgQRlthIgrqPsx/AdeljZWUmOBL2qk`.
Keep strict host-key checking, the original alias, IdentitiesOnly and BatchMode;
do not accept a new key or alter global known_hosts. Record the new boot UUID.

Read-only preflight requires Ubuntu24.04/x86_64, the selected instance identity,
the exact original lifecycle file hashes, active/enabled original four-hour
timer with no changed unit/drop-in, and no active same-name test session. The
boot must differ from all three historical qualification boots and the
read-only retrieval boot. Verify immutable historical bytes/inodes, all19 raw
run0003 cases and original versions/phases; do not instantiate any old Ec2Run,
call `_live` or regenerate an old receipt on a new boot.

All new v3 plan/consumption/run/source/stage/operation/transfer paths must be
absent. Existing or partial files are a refusal, never a cleanup instruction.
Inspect current AppArmor/userns controls without unloading a profile, changing
global policy or weakening an isolation gate. A preflight refusal is not a
probe PASS or an implicit retry. Retain it and ensure automatic Stop.

## Stage and launch once

Stage into new root0700
`/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3`, with scripts0500 and
Stop0400, safe root-owned ancestry and single-link regular files. Verify actual
Git-bound bytes before and after copying; do not chmod or overwrite an existing
foreign or partial target. Check shell syntax remotely, never by executing the
project on the owner's local computer.

Begin an independent pinned journal reader before the sole launch. The existing
launcher remains the entry point:

```text
sudo /usr/local/sbin/tickwitness-run-tests /home/ubuntu /usr/bin/sudo /bin/bash \
  /var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3/run_ec2_reference_recovery_v3.sh \
  SOURCE40 ec201aab11254e8bb7cd1573a96a0004
```

The thin shell execs the root1500s watchdog with2s forced termination, which
supervises the actual Python Controller master after SSH loss. Before
preparation, the controller exclusively creates/fsyncs the fixed operation
directory and start record. An existing/partial operation permanently prevents
another controller, including failure before a qualification claim.

Preparation has one480s+2s bound. It provisions the exact source with explicit
`--recovery-v3`, preserves global controls, exclusively copies Stop and publishes
the fixed v3 plan. The qualifier is called at most once under a612s+2s host
watchdog. Its original600s admission/30s setup/10s per-probe+2s stop gates remain
unchanged; the extra12s permits only stop/report/receipt convergence. Every
phase is also capped by the original1500s outer deadline.

The factory holds the original host claim read-only with a nonblocking exclusive
flock. It exclusively consumes v3 permission before new run/IMDS/policy effects.
Partial publication or uncertain acknowledgement leaves the permission used.
Schema3 means version3, not a reset of historical count21. Initial accounting is
current0/cumulative21; full success is current24/cumulative45.

## Download before acknowledging automatic Stop

The master retains the original qualifier invocation/return code and actual
report bytes in exclusive `qualifier-exit.json`. A single direct exporter child
uses the parent call fence and its own consumption fence, bounded by25s+2s and
16MiB. It fsyncs `archive.pending` and publishes `evidence.tar.gz` without
replacing an existing target. No path launches the qualifier or exporter twice.

The same master then publishes exactly one `handoff-ready.json` and waits only
its original at-most120s. Readiness binds the selected source/run/boot, service
InvocationID/MainPID, actual Python master PID/start identity/argv/cgroup, nonce,
archive bytes/SHA and stable stat seal. The nonce is a single32-lowercase-hex
value. It is not a new qualification ticket or renewed deadline.

Use an independent pinned SSH connection to download the **existing archive**.
Do not invoke the exporter again. Preserve original bytes and before/after
remote stat/SHA, require exact local byte count/hash and retain a local durable
copy. Review member names/types/uniqueness and bounded uncompressed size before
inert extraction; never execute an archived member. Preserve actual ready bytes
and their stat/SHA separately. Local inspection uses inert data tools, not the
project's live authority or replay engine.

Compare all new raw cases with their report hashes/lengths, durable tickets,
nonce/source/run/boot/manifest and stop/cleanup evidence. Verify unchanged
before/after history. Independently associate the actual fsynced final report,
durable terminal SHA and receipt generated in the original live boot. The old
18PASS/UNKNOWN result remains unchanged; it supplies no new control result.

Only after complete local download/verification, send one ACK using the exact
observed ready fields:

```text
sudo /usr/bin/python3 -I \
  /var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3/ec2_reference_handoff_v3.py ack \
  --source-revision SOURCE40 --run-id ec201aab11254e8bb7cd1573a96a0004 \
  --boot-id BOOT --invocation-id INVOCATION --main-pid MAINPID \
  --controller-pid CONTROLLERPID --nonce NONCE --bytes BYTES --sha256 SHA256
```

The helper revalidates current master/guard identities, original deadline and
archive seal/hash before exclusive fsynced ACK publication. It need not run in
the unit's cgroup because it is an independent SSH process. Invalid or stale
input writes nothing. Valid ACK lets the master exit into the unchanged
ExecStopPost hook; normal observed qualifier0..255 is retained only with
successful export/ACK. Unknown/signal/timeout/transport failure returns74 while
preserving the original signed/null phase result. A null return code is not0.

Ready, ACK and final `controller-result.json` are later than the original
archive and remain outside it. Download their original bounded bytes separately
when available; never claim they were archived earlier. A lost ACK reply is
UNKNOWN, not permission to resend ACK or export. Complete qualification evidence
already downloaded is not rewritten because a later operational reply is lost.

## Failure, cancellation and final acceptance

Missing/partial/bad-SHA archive means no valid download ACK. Missing ACK expires
the same original wait and the original hook still requests Stop. Export failure
and controller termination retain whatever bytes were committed; they do not
rewrite successful qualification state or grant another invocation. Preserve
partial local data and disk evidence; any later retrieval is read-only and
separately bounded. Never renew a guard or clear a consumption/operation fence.

The fixed cancel command supports preparation/qualification before ready by
checking the existing start record and actual current unit/master identities.
Only a matching boot/invocation/PID/start/argv/cgroup can publish the exclusive
cancel record and cancel the original unit. Wrong/stale identity cannot signal
a process. Do not blindly retransmit an uncertain cancel. SIGKILL safety comes
from the independent original supervisor/Stop hook, not a killed process's
finally block.

Independently refresh AWS and require the same instance Stopped with no
publicIPv4/DNS after completion, failure or cancellation. SSH loss or a Stop
request is insufficient. Retained EBS remains distinct from stopped compute.

Reference acceptance requires all24 new same-source/run/boot/manifest controls
PASS, matching24/45 accounting with no pending/ACK uncertainty/poison, intact
history, actual successful report/terminal SHA/receipt and confirmed cleanup.
Record qualification, export/download/ACK and cloud Stop separately. Any missing
gate retains its uncertainty; no old PASS or unadmitted subset fills it.
Even reference success keeps M1 DISABLED, PR115 Draft/#38 incomplete, independent
human security review NOT_PERFORMED and external-human reproduction0/0/PENDING.
It is not a merge, release or automatic fifth qualification.
