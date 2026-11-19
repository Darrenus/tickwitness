# Restricted reference qualification v1

Selected for S13-02, 2026-11-19 Asia/Singapore; implementation and actual qualification have **not** passed by this document. Story38 keeps16h, S13 keeps10+16+8=34h and existing quality capacity. This contract must be committed/pushed before implementation. It specializes [Execution trust v1](execution-trust-v1.md), not its support or research authority.

The profile is **selected for internal qualification; unimplemented/unqualified until actual evidence; M1 product admission remains disabled**. M0 retains only existing qualified built-ins; M2 remains unsupported. Independent external security review is not performed. External-human research reproduction stays0 attempts/0 successes/PENDING, #24 OPEN; these are distinct gates.

## Scope and trust

The deliverable is an infrastructure reference launcher and fixed synthetic remote probes using that same launcher. It is not an arbitrary command/source runner, new SDK/CLI execution mode, Job/Catalog schema, native adapter, research finding or hosted endpoint. No existing Job `Popen` command is replaced with a runtime CLI. The privileged host harness, bootstrap, selected binaries, OS/kernel and CI VM are trusted; probe code is the adversarial workload. A compromised harness/kernel or malicious host owner is outside this qualification.

Only GitHub Actions remote CPU on **Ubuntu24.04 / Linux x86_64** is the selected reference family. A rolling runner label is not an exact pin. Every actual VM tuple must be observed, hashed and qualified; another image/kernel/binary tuple inherits no success. No project, bootstrap, bwrap or hostile probe executes on the owner's workstation.

## Frozen controls and numbers

| Control | Selected value and scope |
| --- | --- |
| Task identity | Host real/effective/saved UID/GID61184; supplementary groups empty; no retained host privileges; NNP=1 before unprivileged bwrap exec. Reserved identity must not collide with unrelated host work |
| Task ownership | One fresh root-owned cgroupv2 leaf per admitted probe; root controller remains outside it. Only the gated child and its descendants enter the leaf |
| CPU | `cpu.max=25000 100000`: subtree fair-class bandwidth of25,000 microseconds per100,000 microseconds, **rate**, not cumulative CPU-time allowance or exact elapsed prediction |
| Memory | `memory.max=268435456`, `memory.swap.max=0`, `memory.oom.group=1`; cgroup-accounted subtree memory, not an assertion about the host's total RAM or a simultaneous RSS metric |
| Process expansion | `pids.max=32`, including bootstrap/bwrap/probe members charged to the task; not32 additional children |
| Writable filesystem | One host-mounted private tmpfs, `size=16777216,nr_inodes=512`; its entries/metadata consume the same filesystem's capacity. `/tmp` and `/dev/shm` alias directories on that scratch, not additional writable tmpfs mounts |
| Single file / descriptors | Hard=soft `RLIMIT_FSIZE=8388608`, `RLIMIT_NOFILE=64`; `RLIMIT_CORE=0`, `RLIMIT_RTPRIO=0`, set before unprivileged exec. Single-file size is distinct from the16MiB aggregate scratch limit |
| Probe deadline |10 seconds from its original host monotonic admission, including setup/start/delivery; no renewed window on heartbeat, child fork, readiness or retry |
| Stop confirmation | At most2 seconds of separate kill/confirmation grace; does not extend compute admission or promise physical kernel/IO completion |
| Output | Retain at most65,536 bytes **per stdout and stderr stream**, pumped without unbounded accumulation; overflow stops the task and remains explicit |
| Qualification admission | At most24 fixed synthetic probe admissions within one original600-second host monotonic window. Failed/uncertain launches consume admissions; no hidden retry/reset or unbounded subprocess chain |

Host capture logs are outside the guest16MiB scratch and have their separate per-stream bounds. Host TCB/input preparation, manifest/evidence files, read-only code and shared kernel/runtime accounting are not falsely described as guest scratch consumption or a host-wide disk quota. The600-second value bounds qualification admission, not a universal physical-return/fsync guarantee; later probes stop when it expires.

## Launch order and required mechanisms

1. The trusted host controller validates the selected tuple/capabilities and creates only its own cgroup, private tmpfs, read-only input/TCB view and bounded capture records. It writes/readbacks all required controller values before authorizing a payload. It does not delegate cgroup control files or the privileged harness to the task.
2. A trusted child waits behind an admission gate. The controller places and independently verifies that actual owned child in its leaf **before** UID/GID/groups drop, unprivileged bwrap exec or any probe code. On attachment/control failure, no probe is admitted to run outside the leaf.
3. Bootstrap applies the declared rlimits, empties groups, drops host UID/GID to61184, sets NNP, and execs the selected non-setuid bwrap. The controller records actual identities; namespace UID mapping is observed separately, not invented from the host numeric UID.
4. Require mount isolation and explicit **required** user, PID, IPC, network, UTS and cgroup namespace creation. Use the required `--unshare-user`, `--unshare-pid`, `--unshare-ipc`, `--unshare-net`, `--unshare-uts`, `--unshare-cgroup` forms, plus `--disable-userns`, `--new-session`, `--cap-drop ALL` and `--clearenv`. Do not use `--unshare-all` or `*-try`: optional fallback is insufficient here.
5. Root, `/proc`, `/usr`/runtime TCB and `/input` are read-only. Root remount is **not recursive**: independently inspect every guest mount and writable path. `/dev` contains only descriptor aliases and the scratch-backed `shm` alias, no device nodes. No home, host socket/device, credential, original data/store/registry/ledger/Catalog or other RW tmpfs is exposed. Cwd is private scratch; environment is an explicit minimal allowlist, not inherited host values.
6. Apply the selected seccomp filter before final probe exec. Final payload inherits only stdin/stdout/stderr; the BPF setup descriptor is consumed/closed, and all bootstrap/gate/cgroup/host-canary FDs are absent. No trusted preflight/manifest step itself creates research authority.

Missing namespaces/controllers, an unsuitable setuid/privilege configuration, NNP/AppArmor/userns startup failure, or missing mount/FD/filter proof means **REFUSED / NOT_QUALIFIED / UNKNOWN**, as applicable. Do not retry without NNP, use optional unshare, disable global AppArmor/sysctls, broaden capabilities, skip a required control or run the payload directly as M0.

## Seccomp policy and finite attack surface

Only the native x86_64 ABI is selected. Architecture mismatch and compat/x32 routes must be rejected; a deny rule cannot be bypassed by the x32 syscall-number bit. Freeze the concrete generated rule/number table and BPF digest with the host tuple before probes, retaining unsupported/unknown mappings visibly.

The mandatory denial set covers socket creation/socketpair and network operations; `io_uring_setup/enter/register`; `memfd_create` and `memfd_secret`; SysV message/semaphore/shared-memory IPC; `unshare/setns`, mounting/pivot/modern mount APIs, `clone3` and namespace-creating classic-clone flags; `ptrace`, cross-process VM access, privilege-bearing PID-FD access, `bpf`, performance/userfault facilities and device-node creation. It also denies `sched_setscheduler/sched_setattr` (and equivalent scheduler mutation) so realtime class cannot evade the selected fair-class CPU bandwidth. Ordinary process creation for the bounded process-expansion probe may remain allowed under the leaf's PID controller.

This is a concrete limited reference policy, not a claim that every future syscall/kernel exploit is contained. Any unavailable required rule, unknown architecture/ABI or changed kernel/binary policy requires refusal/requalification, not an inferred pass. Isolated networking alone is not evidence of loopback denial; socket-family/IPv4/IPv6/DNS/loopback/Unix and inherited-FD routes need the actual filter/FD proofs and negative observations.

## Host tuple, observations and output authority

Before the first probe payload in a VM, freeze canonical manifest bytes and SHA-256 binding actual OS/release, kernel, architecture, GitHub runner ImageOS/ImageVersion when observable, Python/libc/bwrap/launcher/probe binary identities and digests, source revision, selected syscall/BPF policy, controller UID/GID, reserved child identity, namespace/mount plan, actual host mounts and controller readbacks, limits and exact fixed-case catalog. Missing observations remain null/UNKNOWN with a reason; no fabricated version, digest or image pin. Save actual bwrap argv and environment allowlist.

Intended launch policy and actual per-child observations are separate. Per-probe host readbacks bind the same manifest hash and record the actual child/cgroup identity, task membership, UID/groups/NNP/capabilities, namespace/mount/FD observations, controller counters/events, stdout/stderr bytes/digests, original clock window, actual exit/signal, stop and cleanup facts. Child self-report is supplementary; a successful exit or claimed policy does not replace independent host observation. Do not backfill unobserved pre-probe facts using a later sample.

Freeze any tuple or required-policy change before new payloads and require fresh qualification. A manifest hash binds observed/configured bytes; it is not a producer signature, hostile-owner attestation, historical timestamp or certification of all runners with the same label.

## Fixed probes and T01–T08 acceptance

The implemented catalog is a closed allowlist of at most24 named synthetic cases, fixed in source and manifest before execution; it cannot accept caller-supplied shell, source, mount, image, resource override or arbitrary path. Each case declares expected denial/positive result and evidence. Counter exhaustion, skipped cases or unknown observations cannot satisfy the matrix.

| Threat | Required actual evidence within the selected scope |
| --- | --- |
| T01 filesystem boundary | Authorized read succeeds; forbidden host/control/input writes and outside reads/link/rename paths are denied; host protected canaries and original roots unchanged |
| T02 source/TCB boundary | Only fixed probe/TCB bytes execute; read-only TCB and input cannot be replaced. No arbitrary strategy execution, source registration privilege or native research run is claimed |
| T03 credentials/network | Secret/environment/FD canaries absent; socket families, DNS/loopback routes and inherited socket/file descriptors cannot reach the host. Record real denial/filter evidence, not only absence of an application listener |
| T04 process/FD/output expansion | Real fork/detach attempts stay in the owned task cgroup, PID/FD ceilings apply, output caps stop flooding, and host observation confirms stop of the complete task membership |
| T05 resource exhaustion | Actual CPU throttling and denied RT promotion, bounded memory/OOM-group behavior,8MiB file bound, multi-file16MiB and inode512 exhaustion are independently observed. Exit137 alone does not prove an OOM cause |
| T06 forged output/authority | Malformed/forged output cannot alter host policy or protected evidence; host-owned observations decide qualification. This does not newly qualify research publication/finding semantics |
| T07 budget boundary | Probe launcher does not construct/open Job/Catalog/research stores, reserve/publish an attempt, run a replay engine or issue a finding; protected original evidence hashes remain unchanged. No product integration is inferred |
| T08 stop/reclaim | Timeout, ignoring task signals and detached descendants are stopped through the owned cgroup; unknown kill/cleanup preserves diagnostics. Cleanup remains within the proven owned mount/cgroup and never deletes original roots |

Positive cases must prove the launcher actually ran inside the intended controls. Negative cases must show actual denial/enforcement without host contamination. Missing proof, startup/refusal, unsupported capability, malformed record or uncertain stop is **not** a successful negative test. A scoped test pass is operational evidence, not a counterexample to a market claim.

## Stop, uncertainty and reclaim

The root controller stays outside the task leaf so task OOM/PID/CPU pressure cannot consume its own task allocation or privilege. Own task membership by current cgroup identity and live child handle, not a historical numeric PID. On timeout/overflow/error, use the owned leaf kill mechanism and bounded wait/reap plus actual `cgroup.events`/membership confirmation; a sent signal, group leader exit or client exit is insufficient.

Stop-requested, stop-confirmed and cleanup-confirmed are separate observations. Preserve bare signals/errno and controller counters without guessing their cause. If task membership or stop remains unknown after2s, report unconfirmed, stop later admissions and retain the owned resources/diagnostics for explicit recovery; do not delete live scratch or silently launch a replacement.

Unmount/remove only the exact owned scratch after confirmed task absence, then remove the empty owned leaf. No lazy/force unmount, broad cgroup kill, stale-PID signaling, global prune or generic recursive deletion of caller paths. Failed unmount/removal remains explicit and cannot become cleanup-confirmed. Publication/IO uncertainty does not grant an automatic probe rerun.

## Original research budget and future integration

These probes consume **zero research reservations and zero replay-engine invocations**; native OS/bootstrap helpers are technical qualification, not native market replay. The24/600 qualification admissions do not grant attempts to any protocol. Original protocol/Job/family identities,5/8/11-slot fixtures, frozen attempts/events/native wall limits, golden and PR94 remain unchanged: no reset/refund/committed-result rerun.

Any future actual built-in integration needs a separately frozen lifecycle/admission/resource mapping. It cannot substitute a runtime client PID for compute ownership, apply existing wait4 metrics to an unrelated launcher, or assume Job bootstrap/lifetime FDs cross another backend unchanged. Preserve core-only ACK/committed-result short circuits; reject unavailable isolation before new original reservation, recheck at launch, and retain an already consumed/uncertain slot on later failure. Real re-execution requires a new slot from the same original budget; committed outcomes are only independently reverified/ACKed.

Qualification success under this exact tuple does not open M1 product admission, add arbitrary-source support or enable M2. Independent security review and the remaining [execution trust gates](execution-trust-v1.md#acceptance-and-enablement-gates) remain separate. All implementation tests, negative probes, builds and native execution run only on the authorized remote CPU profile; actual current-head results must be recorded after they occur.

## Primary mechanism references

- [Linux cgroupv2](https://docs.kernel.org/admin-guide/cgroup-v2.html): controller scopes, CPU bandwidth, memory/PID accounting and task-group observation; actual availability/readbacks still require the selected host.
- [bubblewrap upstream manual](https://github.com/containers/bubblewrap/blob/main/bwrap.xml): required versus optional namespace flags, userns disable, clearenv, FD/seccomp and non-recursive read-only remount semantics. The actually used binary/digest is recorded, not inferred from upstream main.
- [Linux seccomp filter](https://docs.kernel.org/userspace-api/seccomp_filter.html), [no_new_privs](https://docs.kernel.org/userspace-api/no_new_privs.html) and [tmpfs](https://docs.kernel.org/filesystems/tmpfs.html): mechanism boundaries, architecture checks and storage/inode scope, not an existing TickWitness qualification.

## Implementation status after the freeze

The internal adapter and fixed probes are implemented as a candidate. [Actual remote evidence](../security/restricted-reference-evidence-2026-11-19.md) records a pre-load refusal: the selected VM does not expose a complete executable-attachment conflict closure. This reference is NOT_QUALIFIED; the full probe matrix, policy transition and product M1 remain unqualified/disabled. The original frozen controls above are unchanged.
