# One-use EC2 recovery operations

This procedure implements the separately frozen
[recovery contract](../contracts/restricted-reference-ec2-recovery-v1.md) /
[ADR0048](../adr/0048-one-use-ec2-recovery-qualification.md). It is internal
trusted-owner preparation and fixed synthetic qualification. Product M1 stays
DISABLED, external-human reproduction0/0/PENDING and human security review
NOT_PERFORMED. This procedure's existence is not another completed host run.

## Prepare while the instance is stopped

Select the actually pushed, independently reviewed implementation revision after
its remote source checks complete. It must contain the corrected input-directory
permissions and the guarded recovery path. The earlier c59b3e4 correction alone
cannot bypass the permanent host claim. Keep all historical actual-run and source
CI evidence, including their checksum indexes, unchanged in their private scopes.

Construct a concrete package containing the exact committed
`scripts/provision_ec2_reference_source.sh`,
`scripts/run_ec2_reference_recovery.sh` and the2322-byte historical private
`CONTROL-PLANE-OBSERVATIONS.md` under the packet name `operator-stop.md`, plus
source/run selection and actual SHA256/size metadata. The shell batch pins the
provisioner's actual byte hash; if those bytes change, review and update that pin
before the implementation checks. Do not execute project code, Python, formatter,
tests, attacks or provisioning on the owner's workstation.

The one selected run is `ec201aab11254e8bb7cd1573a96a0002`, plan
`ec2-recovery-20261126-v1`. The user starts only the existing selected instance
after this package is ready. No new key, IAM role, security-group expansion,
listener, disk formatting, GPU or replacement instance is part of preparation.

## New boot and guarded stage

Read back the actual AWS account and instance and its new current address. Verify
the original pinned SSH host key. Read-only preflight must confirm the selected
Ubuntu/x86_64 host, a boot different from the predecessor, active/enabled original
4h stop timer without a shortened override, and no active test session.

Confirm all preserved predecessor bytes match the contract's fixed hashes and
that its1charged/1confirmed terminal failure has no pending/ACK-unknown outcome
and confirmed stop/cleanup. Existing plan, global consumption, successor run,
successor source anchor or operation-directory state is retained and refused;
never make a reused host appear fresh by deleting or renaming it.

Stage the reviewed package into the fresh root-owned0700 directory
`/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v1`, scripts0500 and the exact
operator observation0400. Verify root ownership, safe ancestry, no symlinks,
actual SHA256 and remote `bash -n` before launch. Check timeout/prlimit/tar/base64
and observed journald line/rate configuration for the bounded archive transport.
The observation is trusted owner evidence; its digest does not make it a signed
AWS attestation or live cloud readback.

Start an independent read-only journal follower for the current boot **before**
launch, capturing the full fixed unit stream privately. It does not own the job.
Run the fixed batch through the existing verified lifecycle entry, substituting
only the reviewed40-hex implementation revision:

```text
sudo /usr/local/sbin/tickwitness-run-tests /home/ubuntu /usr/bin/sudo /bin/bash \
  /var/lib/tickwitness-lifecycle/ec2-recovery-batch-v1/run_ec2_reference_recovery.sh \
  <actual-reviewed-source40> ec201aab11254e8bb7cd1573a96a0002
```

The batch verifies the pinned preparer, retains its own exact source and creates
an exclusive operation directory. Trusted package/Git preparation precedes the
qualification claim; pre/post global userns controls must remain identical and
already enabled. `--recovery` selects the new exclusive ten-file source-lock kind;
default provisioning retains its nine-file v1 kind. No existing source anchor is
overwritten, and the qualifier never installs packages or enables controllers.

The exact historical Stop observation is installed exclusively under the fixed
root recovery-evidence path. The trusted preparation helper verifies actual new
source closure, historical state and that observation, then writes the one fixed
plan exclusively. Preparing this plan makes no metadata request, policy load,
probe, research reservation or new600s qualification claim.

The driver explicitly selects the frozen recovery plan. Its factory captures
the one new600s/30s anchors before validation, holds the historical host claim's
read-only exclusive flock and durably consumes the global additional invocation
before creating the successor run or accessing metadata/policy. The ordinary v1
entry still refuses the preserved old claim; a new run ID is not recovery authority.

## Evidence, accounting and shutdown

The successor must run all24 fixed cases on one actual source/manifest. Its
initial manifest binds current0/cumulative1; the final report and re-read terminal
receipt must bind actual final24/cumulative25 for success. Plan, predecessor,
consumption and original current-run anchors remain identical across records.
Each current case must match its durable ticket/nonce/outcome and actual raw-file
digest. No old failed result, remaining23-case subset or mixed revision can qualify.

On failure or uncertainty retain the predecessor, one-use consumption, successor
state, partial cases and accounting. Unknown counts are not stale zero; lower
bounds stay labelled. No automatic retry, third window, claim replacement,
refund, policy unload or force/lazy cleanup is supported. Another correction
does not itself grant another host run.

Before lifecycle Stop, the batch exports a host-only bounded archive containing
operation logs, plan/consumption, operator observation, new run/source anchor and
the exact predecessor claim/run/source lock. Generation has a separate25s+2s
transport ceiling and16MiB per-file bound; it neither renews qualification time
nor reserves a probe. Verify one run-bound BEGIN/END pair, decoded byte count and
SHA256, with no EXPORT_UNCERTAIN marker. Missing data means UNKNOWN; preserve
host evidence without rerunning execution. Treat archive members as inert data.

The already verified lifecycle wrapper owns automatic Stop after completion,
failure or cancellation. Independently read back AWS **Stopped** afterwards;
SSH exit or a stop request is insufficient. Retained EBS remains billed.
Even a complete exact-tuple result is only QUALIFIED_REFERENCE_ONLY. Product
integration/security gates and the independent external-human attempt remain
separate; #38, Draft status and public claims must follow actual evidence.
