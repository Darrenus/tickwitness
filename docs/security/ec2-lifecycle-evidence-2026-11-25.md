# EC2 automatic-stop acceptance — 2026-11-25

The dedicated Singapore CPU instance completed its operational lifecycle
acceptance. This is **not M1 isolation qualification**. Product M1 stays DISABLED;
independent security review stays NOT_PERFORMED; external-human research
reproduction stays0/0/PENDING. All execution occurred remotely. No research
reservation, replay invocation or qualification probe was consumed or reset.

## Observed scenarios

The original initialization and successful detached smoke had already completed
and retained their result after Stop/Start. Four additional boots exercised:

| Scenario | Actual host evidence | Independent AWS observation |
| --- | --- | --- |
| Failure and overlapping launch | Primary exited7; second launch refused, second marker absent; original InvocationID and4h deadline unchanged | Stopped, instance-initiated shutdown |
| Cancellation | Independent cancel intent/firing bound to boot, nonce and original InvocationID; actual killed/TERM result and completed service stop | Stopped, instance-initiated shutdown |
| Inactive primary timer | Persistent timer stayed enabled; launcher returned78 without starting payload | Stopped, instance-initiated shutdown |
| Shortened primary timer | Temporary `/run` override; primary stop service Starting/Finished in one InvocationID before emergency deadline | Stopped, instance-initiated shutdown |

Final readback began2026-11-25T13:17:30Z (21:17:30 Asia/Singapore), boot
`5df7cb77-c793-4936-b9a3-57f0fec769dc`, readback nonce
`e011aabb11254e8bb7cd1573a96a0005`. All13 assertions passed. The corrected
historical journal queries returned0 and7/8/3/10 records respectively, each bound
to its exact boot. They positively support the scenario events and show no
emergency-service execution; no emergency receipt was present. Short-timer primary
activation112584659000ns lies between the scheduled111999617930ns and emergency
166792198413ns deadlines in that boot.

The final boot confirmed the runtime override absent, unchanged persistent timer
bytes, and the original4h timer enabled and active. The separate root observer
exported its fsynced full JSON between BEGIN/END markers before poweroff;
runtime423ms, exited0. Afterwards AWS independently showed **Stopped** with
`Client.InstanceInitiatedShutdown`. SSH loss or a shutdown request was never used
as a substitute for that control-plane observation.

## Retained validation defect and correction

The first observer supplied hyphenated kernel UUIDs to `journalctl --boot`.
This systemd rejected the descriptor with return1 and empty output. The observer
wrongly allowed that return code, so its earlier A/B/C host PASS labels are
**withdrawn**. Their raw receipts and failed queries remain unchanged; an export
was retained before correction. This was an evidence-validation defect, not a
reason to rerun or refund the original scenarios.

The reviewed replacement allows only readback. It converts a strictly validated
canonical UUID to32hex, requires return0 and1–119 valid objects with matching boot
IDs, and refuses empty, malformed, wrong-boot or tail-limit-saturated journals.
It checks positive events and same InvocationID where applicable, writes new
assessments only in the final boot's directory, and exports the complete result
before requesting shutdown. It preserves the original80s observer window and90s
emergency safeguard. All source review was static locally; compilation, help-entry
and acceptance execution occurred only on EC2.

| Retained artifact | SHA256 |
| --- | --- |
| Original observer | `3f63940104dd02d62ba38b5fa62ef8d09f8fe74119ac386ff64479abb1163c3c` |
| Original remote archive before correction | `81679572ad238dd53ffceb886093db70da1160009089f5ab21f3e778bb7158c8` |
| Readback-only replacement | `07b58d7de1686cc54283f3eff5ebe17d758fc35f061bd1de8567ce284464a7cf` |
| Complete captured final receipt | `94b90269f78a1b1cfb48f671d8f5753ae9e1e4ed8d00d74c345e30183016f1e3` |
| Complete SSH/systemd stream | `45ee437982ab502323ac1c532877ca666d724441d066e0da96c610e877e79345` |
| Independent corrected historical journals | `7040290dccd31acde1f576a6053fca81d8962eeb916f06bd86cd5670913a5640` |

The raw operational archive stays outside the public source tree. Existing sealed
PR114/PR115 evidence was not modified. The empty raced inactive-timer transfer is
retained as invalid, alongside the subsequently recovered actual refusal78 proof.

## Qualification boundary

This proves the observed stop paths and timer restoration, not an elapsed4h test,
an absolute AWS charge cap, kernel-hang tolerance or execution isolation. Retained
EBS remains billable while stopped. Read-only inventory found Ubuntu24.04.5,
kernel7.0.0-1018-aws, Python3.12 and enabled cpu/memory/pids controllers; bubblewrap
and syscall headers were absent. Trusted provisioning must supply and bind those
dependencies before the [separate EC2 qualification](../contracts/restricted-reference-ec2-v1.md).

The reference contract and ADR0047 were then actually pushed as
[`5a86b8a`](https://github.com/Darrenus/tickwitness/commit/5a86b8a98d815da609b540f0ef91f9605ae3bcf0),
and the remote PR115 branch was read back at that exact SHA before implementation.
No policy load, isolation probe or M1 qualification pass is claimed here.
