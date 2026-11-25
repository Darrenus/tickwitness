# Dedicated EC2 reference operations

This internal procedure implements the [frozen EC2 contract](../contracts/restricted-reference-ec2-v1.md).
It runs only the closed synthetic catalog on the selected owner-trusted CPU host.
M1 product admission remains DISABLED; M2 is unsupported; external-human research
reproduction stays0/0/PENDING and independent security review staysNOT_PERFORMED.

## Preparation before an admission

Complete the [automatic-stop acceptance](ec2-lifecycle-evidence-2026-11-25.md)
first. Keep the instance stopped during source editing and remote CI. Before a
qualification boot, select an actually pushed, reviewed40hex implementation
revision and one explicit32hex run ID. Read back the original AWS account and
instance, then verify the pinned SSH host key at its current address. No new
credential, IAM role, listener, GPU or security-group expansion is part of this
procedure. Starting the existing instance remains an operator action.

Stage the reviewed preparation/batch scripts with their actual source digests.
Run the batch through the previously verified `tickwitness-run-tests` lifecycle
wrapper: its completion/error/cancellation hook requests Stop and the persistent
4h boot timer remains the independent safeguard. The root qualification controller
is a trusted component of that batch, not a guest command selector.

[`provision_ec2_reference_source.sh`](../../scripts/provision_ec2_reference_source.sh)
requires root Ubuntu24.04/x86_64 and an enabled/active stop timer. It installs
official Ubuntu bubblewrap, syscall headers and Git before any claim; it never
loads policy, formats a disk or enables global cgroup controllers. It checks out
the exact commit under `/opt/tickwitness-reference/<revision>`, verifies actual
HEAD and a clean working tree, then creates the exclusive root-owned source lock
under `/var/lib/tickwitness-reference-ec2/sources/<revision>/source-lock.json`.
Existing checkout/anchor state is retained and refused, never overwritten.

The lock binds nine selected controller/loader/backend/bootstrap/payload/policy
files. These hashes do not authenticate every transitive package import or the
full OS runtime; the clean repository, root provisioner, kernel and runtime remain
trusted. The qualifier validates actual root ownership, ancestry and bytes from
the lock, rather than accepting caller-supplied GitHub environment fields.

## One qualification invocation

The fixed entry is `scripts/qualify_restricted_reference_ec2.py` with only
`--source-revision` and `--run-id`. The driver exclusively claims the persistent
host/run record before setup. Claiming captures the original600s qualification
window and30s/3-command policy setup window once; loader and backend join those
same anchors. The fixed IMDSv2 PUT/GET has one combined hard5s deadline and bounded
bodies; the token is neither persisted nor passed to a child.

Policy staging and receipts live in that run directory, outside the boot policy
autoload directory. One explicit add authorizes the frozen named profile; foreign
opaque attachments retain their actual UNKNOWN observations. Root bootstrap and
guest labels must both be independently observed before GO. The old GHA policy
and its opaque-closure refusal remain unchanged.

The driver durably reserves each of the original24 fixed cases before the backend
accepts its ticket once. Each ticket owns its original10s deadline and separate2s
stop confirmation. Constructor recreation, a new nonce, failed publication or a
reboot cannot reset clocks or counters. Uncertain writes/outcomes fence admission;
reports distinguish backend ACK uncertainty from pending probe outcomes, and
never report a stale zero as authoritative after a persistence failure.

Complete success requires both the fsynced final report and its matching hash in
the durable terminal record, verified again by the terminal receipt. A report or
terminal status alone cannot authorize acceptance. Partial/unknown/failed cases
remain NOT_QUALIFIED; expected limit terminations still need the original full
host-evidence assessment, confirmed stop and cleanup. No automatic recovery or
second run is supported; any later recovery needs a separate reviewed plan and
preserved original records.

## Evidence and shutdown

Retain bounded source-lock, raw identity, pre-load/setup/final manifests, run
state, per-case streams/results and final report in a fresh audit scope. Do not
publish raw host evidence or write sealed historical PR114/PR115 archives.
Technical qualification consumes zero research reservations and replay calls;
protocol/Job/family budgets and5/8/11 fixtures remain unchanged.

After the batch exits, read back the AWS control-plane **Stopped** state. A shell
exit, lost SSH or a stop request is insufficient. Keep partial records after any
failure; do not delete claims or uncertain cgroups/mounts to make a retry appear
fresh. Retained EBS remains billable. Even an exact-host
QUALIFIED_REFERENCE_ONLY result does not enable the product M1 gate or replace
independent security review or external-human research reproduction.
