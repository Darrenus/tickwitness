# One-use corrected EC2 qualification operations v2

This procedure implements [recovery v2](../contracts/restricted-reference-ec2-recovery-v2.md)
and [ADR0049](../adr/0049-one-use-corrected-ec2-qualification.md), frozen and
actually pushed/read back at `5ef1945c154cc944900a6d042f947bba0d620fd9` before
implementation. It permits only plan `ec2-recovery-20261127-v2` and run
`ec201aab11254e8bb7cd1573a96a0003`. It does not report an actual v2 host result.
Product M1 stays DISABLED, PR115 Draft/#38 incomplete, human security review
NOT_PERFORMED and external-human reproduction 0/0/PENDING.

The [first recovery](ec2-reference-recovery-evidence-2026-11-26.md) remains
NOT_QUALIFIED and consumed. Original run0001 and recovery run0002 each retain
their one charged and backend-confirmed admission. Both original clocks have
ended. Neither unused controls, corrected source, source CI nor a reboot reopens
either run. V2 adds only its separately reviewed 24-case/600s/30s allowance;
historical2 plus current actual admissions cannot exceed26. No fourth invocation,
research reservation, replay call or product execution is authorized.

## Prepare the concrete package while stopped

Select an actual pushed, independently reviewed implementation containing the
corrected process-limit observer and the complete v2 path, after its remote
source checks pass. The earlier corrected baseline
`5f1b373f3fd7da5cb513dc8e6cf25fdf316e273c` does not itself contain v2 authority.
Retain earlier host and source CI scopes, including failed or cancelled checks,
unchanged. Run no project code, Python, imports, tests, formatter, provisioning
or qualification payload on the owner's workstation.

Build a private packet from the exact committed
`scripts/provision_ec2_reference_source.sh` and
`scripts/run_ec2_reference_recovery_v2.sh`, the selected source/run, actual file
SHA256/size metadata and the second attempt's exact owner Stop observation under
the packet name `operator-stop.md`. That observation is858 bytes, SHA256
`b6fbd33d2d0c8f9f0da20f31535a13d058785665ee9fc0d70baa4116517f7d6d`.
Preserve its original evaluation-phase wording. It is trusted owner evidence,
not signed AWS attestation or a new live cloud query. The batch must pin the
provisioner's actual bytes; review any changed pin before remote source checks.

Keep the same selected EC2 instance/account/access procedure. No new VM, key,
IAM grant, listener, GPU or security-group expansion belongs to this procedure.
Only start the existing instance after the reviewed packet and source checks
are ready, following the established operator Start requirements.

## Read-only preflight and exclusive stage

Read back the actual AWS account, region and selected instance, its current
address and the original pinned SSH host key. Confirm Ubuntu24.04/x86_64 and an
actual boot different from both historical boots. Verify the unchanged lifecycle
file hashes, active/enabled original4h timer without drop-ins and no active test
session. Check the bounded transport tools and current journald line/rate settings.
An IP address or instance name does not replace the provider identity document.

Read-only validate all frozen history bindings from the contract, including:

- The original host claim and run0001 claim/state/report/case/source lock.
- Run0002 claim/state/report/case/manifest, identity document, policy receipts
  and source lock, plus its existing v1 plan, consumption and embedded context.
- Both terminal failures: one accepted positive admission, durable outcome,
  confirmed stop/cleanup and no pending outcome or ACK uncertainty.
- The original2322-byte Stop observation and both old accounting phases.

The existing v1 consumption is required historical evidence and stays USED;
never remove it to satisfy a freshness check. Confirm the fixed v2 plan,
consumption, Stop destination, run0003, selected new source anchor and new stage/
operation paths are absent before their respective exclusive creation phases.
Existing or partial records are retained and refused. Later phases read-only
validate the exact prepared plan and Stop file; any existing v2 consumption
permanently fences another invocation.

Stage the reviewed packet into the fresh root-owned0700 directory
`/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v2`, scripts0500 and Stop0400.
Verify safe ancestry, root ownership, no symlinks, exact hashes and remote
`bash -n`. Do not overwrite old stages or operation directories. Start and
positively observe an independent current-boot journal follower before launch;
the reader captures evidence and does not own the test lifecycle.

Launch the fixed batch once through the existing verified entry:

```text
sudo /usr/local/sbin/tickwitness-run-tests /home/ubuntu /usr/bin/sudo /bin/bash \
  /var/lib/tickwitness-lifecycle/ec2-recovery-batch-v2/run_ec2_reference_recovery_v2.sh \
  <actual-reviewed-source40> ec201aab11254e8bb7cd1573a96a0003
```

## Preparation, claim and acceptance

The batch retains its exact source and preparer and creates an exclusive
operation directory. Trusted dependency preparation uses the explicit
`--recovery-v2 <source40>` mode before qualification; the original global userns
restriction must remain1. The new source lock uses recovery_source_lock_v2,
integer schema2, exactly the original nine files plus
`scripts/prepare_ec2_reference_recovery_v2.py`. Default and recovery-v1 source
lock shapes and helpers remain unchanged.

Only the new trusted helper may prepare
`/var/lib/tickwitness-reference-ec2/recovery-v2/plan.json`. It validates the exact
858-byte Stop at the sibling `operator-stop.md`, both fixed history slots and
current source closure while holding the original host claim read-only under
the shared exclusive flock. It creates no qualification clock, metadata request,
policy or probe. It never imports or runs the old preparation helper.

The qualifier selects only `--recovery-plan ec2-recovery-20261127-v2` and the
explicit `Ec2Run.claim_recovery_v2` factory. It captures its original600s and30s
anchors once before validation, retains that same host mutex for its lifetime,
and exclusively creates/fsyncs `recovery-v2/consumption.json` and its parent before
new-run creation, IMDS or policy. The old claim's bytes/inode remain unchanged.
An exception, partial file or failed publication never refunds consumption.

Keep the original per-task controls, independent bootstrap/guest observations,
resource values and stop/cleanup gates. Preserve actual process-limit raw text
and PID on refusal; READY, partial observations and source tests do not establish
GO. No profile unload, global-control relaxation, optional isolation or force/
lazy cleanup is permitted.

All new v2 authority records use integer schema2 and explicit v2 kinds. Public
recovery_context/recovery_accounting fields retain their names. The same immutable
context binds plan, fixed original/recovery history, consumption, current source,
run, boot, owner and original anchors across provider/policy/setup/manifest/report/
receipt. The41-key manifest retains its initial current0/cumulative2 snapshot.
Successful report and receipt instead require current24/cumulative26, all24
same-source/run/boot/manifest PASS cases and each actual raw result matching its
durable ticket, nonce, outcome and report reference. No old case can fill a gap.
Require the fsynced report, durable TERMINAL final SHA and independent matching
terminal-receipt readback before reporting QUALIFIED_REFERENCE_ONLY.

Failure, incomplete controls or uncertainty stays NOT_QUALIFIED. Keep all partial
results and charges; absent evidence is UNKNOWN, and confirmed lower bounds stay
labelled. Do not resume with the remaining cases or obtain a fresh clock/nonce.

## Export and independently confirm Stop

Before automatic Stop, retain a bounded archive of operation logs and exact batch/
preparer sources, new run/source/plan/consumption/Stop, both historical run/source
anchors and the old v1 plan/consumption/Stop. The separate25s+2s transport ceiling
and16MiB bound grant no qualification time or admission. Observe exactly one
run-bound BEGIN/END pair, matching decoded byte count and SHA256, and no
EXPORT_UNCERTAIN. Review archive members as inert data before extraction.
Missing export remains UNKNOWN; preserve host records without rerunning a worker.
Private historical archive/index digests are provenance references, not a claim
that the runtime rehashed private archives that were not transferred to the host.

The verified lifecycle supervisor owns automatic Stop on completion, failure or
cancellation. Independently refresh AWS and observe Stopped afterwards; a Stop
request, successful client exit or lost SSH connection is insufficient. Retained
EBS remains billable. Record the actual outcome without changing either old scope.
Even complete reference success leaves product M1 and the distinct human review,
external reproduction, merge and release gates unchanged.
