# S13-02 owner review handoff

## Owner接受及实际合并记录

Owner已在本次项目对话中明确回复“接受”，接受精确提交`89e12eb3e2e371ea7a4939f277bab57cd3c7843e`及已披露限制。[PR115](https://github.com/Darrenus/tickwitness/pull/115)按正常matching-head流程实际合并为`40aede39b4d7b051b00b0dd604738e736d3f4c25`，由Darrenus于2026-11-27 17:58:53 Asia/Singapore完成；合并树与接受源码相同。必需documentation／engineering通过；实际18 SUCCESS／1非必需legacy REFUSED–FAILURE／0pending保留。Owner接受这一有界交付及已披露例外，不把失败改称通过，不构成对后续PR的全局豁免。

接受范围是内部固定参考、已有后置证据回传与其文档；原expired74／ACK确实不存在、producer fsync未独立观察及未演示新live AWS receive/ACK仍是限制。此次接受既不是独立人类安全复核，也不启用M1或新增资格许可。后续[S13-03审阅／降级准备](s13-03-review-and-degradation.md)与[采用观察](../planning/s13-03-adoption-observation-2026-11-27.md)分别进行；新材料尚非本次接受的源码修订。

## 原接受前交接快照

以下PENDING清单保留为当时的审阅输入；owner接受当前有界交付不自动填写独立安全结论或真人采用证据，也不代表下列未完成的人类审查已执行。

2026-11-27 Asia/Singapore. **Owner acceptance PENDING.**
[PR115](https://github.com/Darrenus/tickwitness/pull/115) is Draft, OPEN and
unmerged; [S13-02 / #38](https://github.com/Darrenus/tickwitness/issues/38) remains
OPEN / in progress. This packet prepares a concrete owner decision before
[S13-03 / #39](https://github.com/Darrenus/tickwitness/issues/39); it records no
approval, merge or completed story.

The implementation snapshot is
[`b5ee94808861ed6eff085f71073bb703bfd7d6f9`](https://github.com/Darrenus/tickwitness/commit/b5ee94808861ed6eff085f71073bb703bfd7d6f9),
against accepted base
[`6c350b9fe32dfed96392edd2b856e937f767e342`](https://github.com/Darrenus/tickwitness/commit/6c350b9fe32dfed96392edd2b856e937f767e342).
Any later documentation commit needs its own recorded remote checks; the evidence
below does not claim an unobserved future head passed.

## Scope the owner is reviewing

The deliverable is an internal, owner-trusted EC2 reference launcher, its closed
synthetic qualification catalog, bounded operational controller and read-only
evidence recovery. The [reference contract](../contracts/restricted-reference-v1.md),
[EC2 specialization](../contracts/restricted-reference-ec2-v1.md),
[v3 contract](../contracts/restricted-reference-ec2-recovery-v3.md) /
[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md), and
[transport contract](../contracts/restricted-reference-ec2-transport-v1.md) /
[ADR0051](../adr/0051-ec2-evidence-receive-and-readback.md) define its authority.
The trusted root controller, host owner, kernel and selected dependencies remain
trusted. A passing tuple does not qualify another image, kernel or binary tuple.

| Boundary | Review scope and retained limit |
| --- | --- |
| Files and identity | Read-only input/TCB, required namespaces, dropped identity/capabilities, NNP, minimal environment and final seccomp; one private writable tmpfs. Named-unconfined AppArmor permits the selected userns transition; it is not additional MAC confinement |
| Resources | Subtree CPU rate `25000/100000`, memory 256 MiB / swap 0 / OOM-group 1, PID 32, scratch 16 MiB / 512 inodes, file 8 MiB, FD 64, CORE 0 / RTPRIO 0; per-task 10s admission plus separate 2s stop confirmation; 64 KiB per output stream. These are scoped controls, not a host-wide quota or physical-return guarantee |
| Authority | Fixed probes consume no research reservations and invoke no market replay. Existing protocol/Job/family budgets, 5/8/11 fixtures, golden, PR94 and committed-result ACK rules remain unchanged |
| Product support | **M1 DISABLED and not integrated into SDK/CLI/Job execution.** Current support remains M0 with already qualified built-in profiles; registered user Python source is not executed. M2 hosted/multi-tenant support, arbitrary strategies and HTTP/MCP listeners remain unavailable |

The [SDK](../../src/tickwitness/sdk.py), [CLI](../../src/tickwitness/cli.py),
[support matrix](../support.md) and
[execution trust gates](../contracts/execution-trust-v1.md#acceptance-and-enablement-gates)
remain the product boundary. No mode selector or new research authority is
created by accepting this internal reference work.

## Evidence to inspect

The [actual v3 qualification and recovered final evidence](ec2-reference-recovery-v3-evidence-2026-11-27.md)
is the primary result record. Historical
[GHA refusal](restricted-reference-evidence-2026-11-19.md),
[first EC2 failure](ec2-reference-evidence-2026-11-25.md),
[recovery-v1 failure](ec2-reference-recovery-evidence-2026-11-26.md) and
[recovery-v2 partial result](ec2-reference-recovery-v2-evidence-2026-11-27.md)
remain separate records, with their original charges and outcomes.

| Evidence class | Actual observation | What it establishes |
| --- | --- | --- |
| Positive qualification | Source `908d56db32439f38686346687a5b43239b1b7264`; all 24 controls PASS; qualifier exit 0; associated report, durable terminal state and original-boot receipt | The fixed catalog completed under the recorded reference tuple and controls |
| Negative qualification | Filesystem/read-only, environment/identity, IPv4/IPv6/DNS/loopback/inherited-FD denial; memory/PID/storage/inode/FD/file/CPU/output limits; detached stop, namespace/syscall/ABI denial and malformed/closed-output cases are included in those 24 controls | Scoped actual denial/enforcement and stop/cleanup evidence; startup refusal alone never counts as a negative PASS |
| Accounting | Current 24 plus retained prior 21 = cumulative 45; pending 0, unconfirmed 0, poisoned=false | No hidden qualification refund/reset; original 24 controls were not rerun during readback; new research reservations, replay invocations and budget resets are each 0 |
| Original transport failure | Qualifier 0 and export 0, followed by an expired handoff and controller 74; genuine ACK absence and cancel absence recovered | Qualification PASS is preserved alongside a failed original handoff. Readback does not backdate an ACK or turn controller 74 into 0 |
| Historical readback | Source `e9ff318efc9ea2c333dcb241d0871150c3d30446`; 12 fixed records: 10 present / 2 genuinely absent; three original journal streams complete; 13 SSH final statuses 0 | Collection closed through bounded existing-record retrieval, with no old ACK, export, qualifier or controller replay |
| Immutability and shutdown | All 558 original file pins and ten source byte/hash bindings unchanged; prior 604-file audit unchanged. AWS independently observed Stopped at 15:08:26 Singapore time, 27 November, no public IP/DNS, guest-initiated shutdown | Recovered evidence retained its original anchors and the readback host stopped; SSH exit alone is not the Stop evidence |

The ten source files have original byte/hash bindings and current before/after
inode stability; their complete original inode set was **NOT_RECORDED**. This
must not be promoted to original inode proof. Hash closures detect differences
relative to retained anchors; they do not authenticate a hostile producer or
prevent an owner/kernel replacing all anchors.

The separately pinned production reader SHA256 is
`764689c94886b4081899d08d965d654c481204d27a907161523f6b86a9b0805d`.
Production bytes at the implementation snapshot are identical to the readback
source. The fresh audit closures are:

| Closed scope | Files | Index SHA256 |
| --- | --- | --- |
| Historical readback | 63 | `24172392588984a1c56fa314f029c630d7ba92bb29a8f60a29d39440c0cf1788` |
| Reviewed reader packet | 10 | `36cd532d365574693554fbce2327cce151f9e2db0ffe355e1669de33f329bdd3` |
| Final source verification | 52 | `111152e4434cac7765681ea6d8ba87685b1b407295c24a243804467e522f9b37` |

These opaque anchors identify retained evidence; this public packet does not
publish private raw logs, source data, credentials or machine access details.

## Remote source checks and their limits

All project execution, imports, tests, lint and builds were remote CPU work.
Preparation of this handoff is static documentation work.

| Run at the implementation snapshot | Actual result | Scope |
| --- | --- | --- |
| [Engineering 45957248416](https://github.com/Darrenus/tickwitness/actions/runs/45957248416) | SUCCESS, 16/16 jobs | Source/installation regressions within the existing support matrix |
| [Dedicated transport 45957248397](https://github.com/Darrenus/tickwitness/actions/runs/45957248397) | 91 PASS / 0 fail / 0 skip | Production reader/receiver, durable fixtures and bounded transport/failure regressions; synthetic CI transport is not another AWS qualification or independent human review |
| [Documentation 45957248501](https://github.com/Darrenus/tickwitness/actions/runs/45957248501) | SUCCESS | Documentation checks at that source snapshot |
| [Legacy reference 45957248387](https://github.com/Darrenus/tickwitness/actions/runs/45957248387) | REFUSED: opaque AppArmor attachment closure | Preserved fail-closed GHA behavior; it does not contradict or inherit the separate EC2 24-control PASS |

The production reader/receiver are
[ec2_reference_reader_v1.py](../../scripts/ec2_reference_reader_v1.py) and
[ec2_reference_receiver_v1.py](../../scripts/ec2_reference_receiver_v1.py).
The actual historical retrieval used the fixed read-only path. The new automated
live receiver has remote regression evidence; a successful new live AWS
receive/ACK is **not demonstrated** by this readback. Its deployment still needs
an independently authorized remote execution surface with existing access.

## Owner review checklist and available decisions

Every item below is **PENDING owner review**. No box is pre-approved, and this
document is not an independent security assessment.

| Review item | Concrete acceptance question |
| --- | --- |
| Boundary and implementation diff | Does the snapshot implement only the frozen internal reference/transport scope, while SDK/CLI/Job integration and product M1 stay closed? |
| Positive and negative evidence | Do the manifest, 24 raw cases and host observations support each required control, including stop/cleanup, rather than merely a child exit or self-report? |
| Unknowns and history | Are the original expired/74 handoff, genuine absent records, earlier failed/UNKNOWN outcomes and source-inode limitation preserved without reinterpretation? |
| Conservation and degradation | Are 45 actual technical charges, zero research activity and original budgets retained, with missing/changed controls refusing admission and uncertain stop preserving diagnostics? |
| Review and support claims | Are automated regressions, reference qualification, owner acceptance, independent security review and external-human reproduction reported as separate gates? |

The owner can request concrete changes, defer acceptance with the missing
evidence named, or explicitly accept the bounded S13-02 deliverable after reading
the diff and evidence under the
[working agreement](../planning/working-agreement.md). Any acceptance must name
the reviewed revision and residual limits in the PR record. PR state, merge and
#38 completion require their own observed owner actions; this packet performs
none of them. Owner acceptance or merge does not satisfy independent human
security review or enable M1.

On missing controls, an unqualified/changed tuple, malformed evidence or uncertain
stop, keep the capability unavailable; do not fall back silently to M0. Preserve
diagnostics and charged/committed history. This handoff grants no new Start,
qualification, export, old ACK, retry window, listener, hosted mode, release,
research budget or outreach.

## Inputs still required for S13-03

S13-03 / #39 remains planned with its original **8h estimate**; S13-02 retains its
original **16h estimate**, and S13 remains 10+16+8=34h with unchanged quality
capacity. These are plans, not actual-hours claims.

Independent human security review remains **NOT_PERFORMED** and reviewer
**UNASSIGNED**. Preparation should carry this packet's trust boundary, attack
catalog, raw-evidence access constraints, unresolved live-transport proof and
fail-closed/degradation rules to an actual reviewer. No external contact is
authorized by this packet. AI review, CI and owner merge do not count as
independent human security review.

External-human research reproduction remains **0 attempts / 0 successes /
PENDING**, [#24 OPEN](https://github.com/Darrenus/tickwitness/issues/24); adoption,
activation and reuse observations remain zero with no invented observation start.
S13-03 must retain that separate register and record real evidence when it exists.
Security preparation cannot substitute for real adoption, and absent review or
adoption evidence is not converted to a completed gate.
