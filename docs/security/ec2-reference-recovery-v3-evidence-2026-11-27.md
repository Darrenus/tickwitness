# Fixed EC2 qualification v3 and completed historical readback — 2026-11-27

Result: **QUALIFIED_REFERENCE_ONLY** for the one fixed run0004: all24 controls
actually PASS. Historical evidence readback is **COMPLETE**. The original live
handoff remains **EXPIRED / exit74 / no ACK**; recovering its records does not
make that handoff successful. Product M1 remains **DISABLED**, owner acceptance
of S13-02 is PENDING, human security review NOT_PERFORMED and external-human
research reproduction0/0/PENDING. See the [owner review packet](s13-02-owner-review.md).

## Authority, source and bounded scope

The [v3 contract](../contracts/restricted-reference-ec2-recovery-v3.md) /
[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md) were committed and
actually pushed as `72c83a02d47a403d5f9d33aad2f84ccaba7ec6a4` before implementation.
The separately frozen [transport contract](../contracts/restricted-reference-ec2-transport-v1.md) /
[ADR0051](../adr/0051-ec2-evidence-receive-and-readback.md), revision
`f2ffcb99b8790aeb703e65e92db4dc9e10e089d4`, authorize only existing evidence
transport, not a fifth qualification, a new research allowance or an old ACK retry.

| Identity | Actual observation |
| --- | --- |
| Qualification source | `908d56db32439f38686346687a5b43239b1b7264` |
| Fixed run | `ec201aab11254e8bb7cd1573a96a0004` |
| Qualification boot | `352c3c3d-d057-4ce8-838d-2f46738624bf` |
| Qualification unit invocation | `4c261176550240faba960a772ebc1048` |
| Selected host family | Dedicated EC2, Singapore, m7i.2xlarge, Ubuntu24.04.5 LTS, x86_64 |
| Actual kernel / runtime | `7.0.0-1018-aws`; Python3.12.3; bubblewrap0.9.0 |
| Historical readback source | `e9ff318efc9ea2c333dcb241d0871150c3d30446` |
| Readback observation | `ec2-readback-20261127-run0004-01` |

The manifest binds actual binaries, policy, syscall/BPF map, identities, mounts,
FDs and environment. Its source and tuple, rather than the EC2 brand or rolling
Ubuntu label, bound this result. Guest controls retain UID/GID61184, cgroupv2
`cpu.max=25000 100000` (bandwidth, not cumulative CPU seconds), memory256MiB,
swap0, tasks32, FDs64, single-file8MiB, private tmpfs16MiB/512inodes and
stdout/stderr64KiB each. Each admission keeps its original10s deadline and2s
stop confirmation; the whole qualification keeps the original600s window.
The trusted root controller remains outside the guest cgroup. AppArmor userns
authorization is not a claim of an additional MAC sandbox. See the
[original reference contract](../contracts/restricted-reference-v1.md) and
[explicit policy contract](../contracts/restricted-reference-apparmor-v1.md).

## Actual control execution and durable accounting

| Fixed controls | Actual outcomes |
| --- | --- |
| 01–05 | positive, filesystem, readonly, environment, identity: all PASS |
| 06–10 | network_ipv4, network_ipv6, network_dns, network_loopback, inherited_fds: all PASS |
| 11–16 | memory, pids, disk_bytes, inodes, fds, file_size: all PASS |
| 17–19 | cpu, output_flood, detached: all PASS |
| 20–24 | namespace_denial, privileged_syscalls, abi_denial, malformed_output, stdio_closed: all PASS |

These are actual nonce-bound payload executions with retained raw case files,
independent host observations, stop/cleanup and protected-canary checks. A
nonzero guest exit alone is not the acceptance criterion. The successful report,
durable terminal and receipt already present in the original qualification
stdout agree; readback did not regenerate that receipt.

Current charged / backend confirmed / payload starts are24/24/24; historical
charged / confirmed remain21/21; cumulative45/45. Pending outcomes and backend
uncertainty are0, poisoned=false, terminal result QUALIFIED_REFERENCE_ONLY.
The initial manifest records its pre-admission snapshot; the final report and
terminal receipt record the actual final24/45 snapshot. Research reservations
and replay invocations are0. The failed earlier runs and their charged slots
remain unchanged, including [run0003's admitted UNKNOWN](ec2-reference-recovery-v2-evidence-2026-11-27.md).
V3 is consumed; neither readback nor this documentation grants another admission.

## Original handoff failure and completed recovery

Preparation, qualifier and export each returned0. The original archive was
published before ready and therefore cannot contain the later controller-result
or ACK. Full desktop verification exceeded the original120s handoff; the sole
ACK connection timed out before authentication and was never resent.

Readback recovered the original canonical controller-result: handoff_status
`expired`, returncode74. `handoff-ack.json` and `controller-cancel.json` are
genuinely ABSENT; the two existing empty stderr files remain PRESENT_EMPTY.
All12 fixed post-records are classified: ten present, including those two empty
files, and two absent. There was no new exporter, qualifier, old-helper call,
authority, clock reset, budget reset or research workload execution during
retrieval. The reviewed production reader itself ran remotely via Python stdin;
desktop work used native SSH and inert byte inspection, with no local project
execution.

All13 authenticated native SSH operations ended0. Complete original journal
queries returned boot2636 records, unit9 and invocation4, each with producer0,
complete framing, retained byte length and SHA. The boot and unit queries
positively record PID1's exit74 for the exact original invocation at
2026-11-27 13:30:43.043621 Asia/Singapore. The invocation-only query excludes that
PID1 record because its manager invocation field differs from the service field.
An empty or omitted query result was not used to infer a successful exit.

The original428942-byte archive is byte-identical to the previously sealed copy.
All558 original remote stat/hash pins and ten source-closure hashes match before
and after retrieval. Original source inode identities were not fully recorded;
the new before/after stability check does not invent that missing history.
The controller-result's complete stable JSON and manager exit74 do not
independently establish whether the original producer's fsync returned
successfully: **NOT_INDEPENDENTLY_OBSERVED** remains the recorded limitation.

The139-byte original shared last-result file was preserved before the unchanged
lifecycle wrapper launched only native `sleep300` in the readback boot. After
the final identity-bound snapshot/inventory, stopping that exact guard invoked
the original ExecStopPost. An independent refreshed AWS observation at
2026-11-27 **15:08:26.552 Asia/Singapore** confirmed **Stopped**, no public IPv4
or DNS, reason `Client.InstanceInitiatedShutdown`. No cloud Start/Stop API was
executed by the agent. That is a dated observation, not a continuous cloud monitor.

## Retained anchors and source checks

Raw host evidence remains in the owner's private, closed audits; this public
summary does not upload machine records, credentials or private paths. SHA256
anchors support consistency against those retained bytes, not independent
authentication against a hostile owner.

| Retained object | SHA256 |
| --- | --- |
| Successful final report,32201bytes | `d9d7d7df17b49314d2eaae989947462b83d5a22344a2883169a06d2cb152e12d` |
| Durable state | `a965a6a2ce0b08a4c5f16dbfbe63615e514e8410ccbac6aaf402724d2fa0af9e` |
| Qualification manifest | `89c21b679b79e2fa61f1b9d2b8543a6b2158e941c2f3dc07ac40127ae89750b8` |
| Original archive,428942bytes | `2b4421e622e0d3a17f0ad3b71495b2285389b6bfaa9fc0879e54e6ebe47230a9` |
| Original controller-result,421bytes | `259a262c1522fa45d5d33885c0f14ed4df6a11dd3a87df83b54090ce37b75149` |
| Original CLOSED604-file audit index | `db1f359f6b9d2a83307388630cdb4b4e9014ef83f4f6b741d344f66074c34a73` |
| Completed CLOSED63-file readback index | `24172392588984a1c56fa314f029c630d7ba92bb29a8f60a29d39440c0cf1788` |
| Readback receipt | `7e4ead262de16ddc3c4c067901e30ff0b31c0865e3a1f38eb0c4bd3ee1ab6b61` |
| Actual reader bytes | `764689c94886b4081899d08d965d654c481204d27a907161523f6b86a9b0805d` |

The604- and63-file audit indexes were independently checked604/604 and63/63;
neither scope was subsequently edited. Qualification source and the original
three operation scripts are unchanged. Production reader/receiver bytes are
unchanged between the actual reader revision and pre-documentation source
`b5ee94808861ed6eff085f71073bb703bfd7d6f9`; the latter fixes only a test's
real-signal thread targeting and does not amend the actual host result.

Remote checks for that exact pre-documentation source:
[Engineering45957248416](https://github.com/Darrenus/tickwitness/actions/runs/45957248416)
completed16/16 SUCCESS;
[dedicated45957248397](https://github.com/Darrenus/tickwitness/actions/runs/45957248397)
completed91 tests,0 failures/errors/skips;
[Documentation45957248501](https://github.com/Darrenus/tickwitness/actions/runs/45957248501)
passed. The separate
[legacy GHA reference45957248387](https://github.com/Darrenus/tickwitness/actions/runs/45957248387)
remains FAILURE/REFUSED because loaded AppArmor attachments were unknown.
It is not AWS failure, skipped acceptance or a waived green check. New
documentation revisions must record their own checks rather than inherit these.

## Acceptance boundary

This completes evidence collection for the fixed internal reference, not
arbitrary Python strategy support, independent security certification or
external-user reproduction. M1 has no integrated CLI/SDK admission path and
remains DISABLED; M2 and hosted listeners remain unsupported. Owner review of
PR115 is still required by the [working agreement](../planning/working-agreement.md).
S13-03's independent-review preparation and adoption observations stay separate;
an owner merge, AI review or CI run counts for neither human gate. The
[Sprint13 status](../planning/sprint-13-status.md) retains all earlier failures
and the original10+16+8=34h planning allocation without invented actual hours.
