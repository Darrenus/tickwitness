# One-use EC2 recovery qualification — 2026-11-26

Result: **NOT_QUALIFIED**. Product M1 remains **DISABLED**, PR115 remains Draft,
and S13-02 / #38 is incomplete. The one additional invocation authorized by the
[recovery contract](../contracts/restricted-reference-ec2-recovery-v1.md) was
consumed. No third invocation, automatic retry or reopening is authorized.

## Actual source and operation

The selected source was `d5f5fab9978d0cb2d1fed92f32552632705d52ee`, run
`ec201aab11254e8bb7cd1573a96a0002`, on a new actual boot. Its preceding remote
Engineering run45832886009 completed all16 jobs successfully, including actual
wheel/source examples and aggregate; Documentation45832885883 also passed.
Six core runtimes each passed4797 tests/112 skipped and two native runtimes each
passed4906 tests/3 skipped. The actual CI merge checkout had the same Git tree
`22cf93fc6dacd999f8b76bb8ca92b8593fdd059c` as the selected source. These are
source regressions, not EC2 isolation acceptance. The separate old GHA opaque
policy refusal remains unchanged.

The owner manually started the existing selected instance at22:40:09
Asia/Singapore. The original SSH host-key fingerprint matched. Read-only remote
preflight confirmed Ubuntu24.04.5/x86_64, kernel7.0.0-1018-aws, the original four
lifecycle file hashes, enabled/active4h timer without drop-ins, and no active
test session. The original claim, failed state/report/case and source lock matched
their frozen hashes. All successor paths were absent. The existing owner-only
TCP22 rule was updated to the owner's current single /32; no additional ingress,
credential, IAM role, server, listener, GPU or research permission was introduced.

The exact reviewed files were staged into a fresh private root-owned directory,
with scripts0500 and the historical Stop observation0400. Hashes, ownership and
remote shell syntax passed. An independent current-boot journal reader was
positively observed before one launch through the existing lifecycle wrapper.
Actual service invocation was `17d5d5889d194c39bb09b7b216090e74`.

Trusted dependency preparation and the ten-file source lock succeeded; all ten
file hashes match the selected Git objects. The global userns restriction stayed1.
The fixed plan and one-use consumption were published; all three policy commands
returned0. Exact plan, consumption, invocation and predecessor context agree
across the new claim/state, provider, policy receipts, manifest, report and stdout.

## Observed refusal and retained accounting

The positive case failed at the independent host process-limit readback gate:

```text
ValueError: Independent hard/soft process ceiling readback differs
```

The named AppArmor transition and bootstrap identity were observed. Fixed Python
also emitted the matching readiness frame. In this fixed source, that frame is
emitted after its self-check of the four resource-limit pairs and before waiting
for the controller's GO. It does not establish independent host acceptance.
The host observer raised before returning `guest_process_observation`, so the
controller sent no GO, left `payload_started=false`, stopped and cleaned up the
task, and ended the invocation. The positive probe body did not run. Its -9 exit
reflects controller cleanup, not a passed resource-exhaustion negative.

| Observation | Actual value |
| --- | --- |
| Historical charged / backend accepted | 1 / 1, unchanged |
| Current charged / backend accepted | 1 / 1, no refund |
| Cumulative charged / backend accepted | 2 / 2 |
| Current pending outcomes / ACK uncertainty | 0 / 0 |
| Remaining fixed controls | 23 unadmitted UNKNOWN |
| Manifest accounting phase | Pre-probe current0 / cumulative1, unchanged |
| Final report accounting | Current1 / cumulative2 |
| Stop / cleanup | Confirmed; task absent, cgroup empty/unpopulated |
| Protected canaries | Unchanged |
| Durable state | TERMINAL / NOT_QUALIFIED; poisoned=true |
| Successful report hash / terminal receipt | null / null |
| Research reservations / replay calls | 0 / 0 |

The actual case SHA256
`572844853e49d00720682332d89a718ee5e424a63252c47998010a37a448cf4a`
matches both its report execution reference and durable outcome. The manifest
SHA256 is `261bd6890d6c064949fa7960916079f72e65316cbfe367472fab57a968a137be`.
The failed report SHA256 is
`ca3048f10484f0bd8c8f1aa7c30db5e672f922fff799ec6b83f7659569b8d5fc`;
its existence is not a successful terminal receipt.

## Complete export and independent Stop

Exactly one matching archive BEGIN/END pair was captured, without EXPORT_UNCERTAIN.
Native base64 decoding produced105501 bytes, with SHA256
`4ade0f15fd75a2ac6e457f798ec55e72880bbffad602d72ded3c9c3b427f692f`.
All252 archive members were reviewed as regular files/directories with safe,
unique relative names before inert extraction. Private raw evidence remains
outside the public source tree. Prior source/run/CI evidence was not rewritten.
The evaluated private scope indexes228 files with checksum-index SHA256
`6516ceb56fbc302484cf391cc0c0434a3414c5e6ad6cb33ccbed06a9b1323571`;
this includes the transport, operation observations and evaluated records.

The journal connection subsequently closed255; a separate read-only progress
connection timed out. Neither transport event is Stop acceptance. A fresh AWS
control-plane refresh independently showed **Stopped**, no publicIPv4 or DNS,
the same22:40:09 launch, and `Client.InstanceInitiatedShutdown`. No agent cloud
Stop or additional Start was issued. Retained EBS remains billable.

## Diagnosis and correction boundary

The failing attempt did not retain the raw `/proc/<guestpid>/limits` text or the
individual failed row. Its exact observed values therefore remain UNKNOWN; the
readiness self-check cannot replace the missing independent raw observation.

A separate static defect exists in the host reader: the first three regular
expressions require `bytes` or `files` immediately at end of line. Upstream
[Linux v7.0 prints the units with a padded column](https://github.com/torvalds/linux/blob/v7.0/fs/proc/base.c#L626-L629).
That layout can be rejected even when both numeric limits are correct. This
supports a formatting diagnosis, but it does not retroactively prove this AWS
kernel's unretained rows or turn the failed case into PASS.

Corrective source work must accept horizontal column padding while preserving
the exact original hard/soft values and units, reject missing/duplicate or
different required rows, and retain the actual raw readback even on rejection.
A real Linux `/proc` producer regression is separate from isolation qualification;
it grants no host claim, GO, research slot or new recovery allowance. Full guest
observation and `payload_started` remain gated by every original independent check.

The old failure and this consumed recovery remain immutable. Another source
correction does not authorize a third host invocation or reuse the remaining23
controls. Product M1 stays closed. Independent human security review remains
NOT_PERFORMED and external-human reproduction0/0/PENDING.
