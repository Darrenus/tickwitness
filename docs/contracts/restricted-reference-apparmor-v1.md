# Explicit reference userns authorization v1

S13-02 compatibility freeze, 2026-11-19 Asia/Singapore. This policy and contract must be committed/pushed before loader or bootstrap implementation. Actual loading, transition and qualification are **not yet passed**; product M1 remains disabled and M2 unsupported.

This specializes [Restricted reference v1](restricted-reference-v1.md) only for one fresh, dedicated Ubuntu24.04/x86_64 GitHub-hosted CPU VM. It is an explicit trusted-host authorization layer, not an SDK/CLI mode, arbitrary-source runner, domain/Job/Catalog change or additional AppArmor MAC confinement.

## Observed failure and remaining uncertainty

The original run44536018240/head `e575a914` remains NOT_QUALIFIED with zero payload starts: bwrap loopback RTM_NEWADDR returned EPERM, without kernel audit evidence on that original VM.

The separate [run44538107915](https://github.com/Darrenus/tickwitness/actions/runs/44538107915), head `56a4377`, yielded three valid records correlated to its own boot/case window: PID2893/bwrap/unconfined `userns_create` AUDIT, then PID2894/bwrap/profile `unprivileged_userns` capability DENIED for cap8/setpcap and cap12/net_admin. These are actual new-VM denials, not retrospective evidence for the original VM.

The collector hit STDOUT_LIMIT and its final line was malformed. Overall audit completeness stays **UNKNOWN**; retain the three valid records and the partial/overflow facts. Do not call the audit complete, infer every intervening event, or count startup refusal as a successful attack probe.

Observed baseline: Ubuntu24.04.5, kernel7.0.0-1017-azure, ImageVersion20261111.370.1, bwrap0.9.0/package0.9.0-1ubuntu0.3. These are observations, not an exact future runner pin. Parser, ABI, libapparmor and new-VM identities are not yet captured and must not be invented.

## Exact policy and pre-load binding

The sole selected source is [reference-bwrap.apparmor](../../research/security/reference-bwrap.apparmor): ABI4.0, named profile `tickwitness-reference-bwrap`, exact executable attachment `/usr/bin/bwrap`, `flags=(unconfined)` and only `userns,`. No additional include, local override, wildcard attachment, capability allowance or transition rule is authorized.

Named-unconfined authorization is not enforce-mode MAC confinement. Attachment is not intrinsically limited to UID61184 or the setup instant; bootstrap/bwrap descendants may retain this named label. The exclusive disposable VM bounds that broader host-policy effect; no shared server or owner workstation is selected.

Before loading, write a canonical pre-load manifest and SHA256 containing:

| Binding | Required actual fields |
| --- | --- |
| Host | Actual OS/kernel/architecture, ImageOS/ImageVersion when observable, source revision and existing reference tuple identities |
| Policy | Exact source/staged bytes and SHA256, profile name/attachment/flags, root-owned non-symlink input identity and selected policy namespace |
| Parser | Actual absolute path/realpath, version/package/digest, exact argv/deadline/output bounds, parser configuration bytes/digest or explicit absence, ABI4.0 bytes/digest and resolved input closure |
| Kernel policy | Actual AppArmor enablement, policy features/ABI observations, global userns restriction and pre-existing loaded profiles/attachments; unknowns retain reasons |
| Transition TCB | Actual absolute libapparmor path/realpath, ownership/mode and bytes/digest, required `aa_change_profile` symbol, fixed target and expected before/after labels |

Missing required policy/ABI/library/control evidence or inability to establish absence of a conflicting name/attachment means REFUSED/NOT_QUALIFIED. Do not substitute a guessed package version or treat a source hash alone as proof of the loaded kernel policy.

Policy setup has one original30-second monotonic window, including preparation and at most3 fixed external commands: parser version, dpkg-query for the selected apparmor/libapparmor1/bubblewrap package versions, and one parser add. Each command stdout/stderr retains at most65,536 bytes; timeout/overflow/unknown is not retried. Kernel feature capture permits at most256 regular files, at most4096 bytes each and1MiB total; ABI4.0 and parser configuration are each at most65,536 bytes. Canonical pre-load manifest and setup report are each at most262,144 bytes, in a separate root-owned evidence directory; binary digests may be streamed. Missing required inputs, replacement or ambiguous conflict refuse setup. These trusted-host preparation bounds do not renew any original probe deadline or admit another probe.

Load only this fixed policy through the frozen parser with **add** and **skip-cache** semantics, bounded host deadline/output and retained actual exit/errno. A same-name profile or conflicting/ambiguous bwrap attachment must be refused, never replaced, disabled or silently reused. No global reload, cache purge, policy teardown, AppArmor/sysctl disable or broad policy-directory load is authorized.

Require actual loaded name/mode readback and unchanged global `apparmor_restrict_unprivileged_userns=1`; preserve before/after observations. The controller stays outside the task leaf and outside the named task profile. A loader success alone is not a transition, payload start or qualification pass.

## Explicit transition before NNP

1. Keep the original gated launch: create the owned leaf/scratch, write/read back original controllers, attach and independently verify the live trusted child before releasing its first gate.
2. After that attachment/readback, while this fixed bootstrap is still trusted root and **before** UID/GID drop or setting NNP, use only the bound libapparmor to call `aa_change_profile("tickwitness-reference-bwrap")`. Record actual pre/post labels, return/errno, library binding and cgroup identity. Do not assume a later exec can relax LSM policy under NNP.
3. Require the expected named-unconfined label, preserving raw observations and independent host readbacks at the gates. Failure, an unexpected label, missing library/symbol or an already incompatible NNP state refuses launch; no fallback or alternate command is allowed.
4. Then perform the original fair-scheduler/rlimit setup, groups=[], irreversible host UID/GID61184 drop, NNP=1, zero retained host capabilities and parent/ownership checks; independently verify the dropped bootstrap before its next gate.
5. Exec the same non-setuid bwrap with all required namespaces, `--disable-userns`, `--new-session`, `--cap-drop ALL`, clearenv, original read-only mounts/FD rules and final seccomp. No adversarial payload executes before those controls.
6. Observe the actual final guest label, identities, capabilities, namespaces, mounts, FDs, scheduler, filter and controller readbacks before GO. Plain/unexpected labels or lost controls are NOT_QUALIFIED/UNKNOWN, not a successful negative.

The library transition itself is trusted setup, not memory isolation or FD remediation. Keep original exec boundaries, strict descriptor closure and no secret/control paths exposed. Do not remove NNP, grant task host capabilities, weaken the final filter or use optional namespaces to make this profile work.

After loading, freeze the actual complete reference manifest before probes, binding the pre-load manifest, loaded-policy readbacks, fixed transition policy and the same actual binaries/library/ABI/policy. Actual per-child transition observations bind that manifest hash before GO; they are not invented as pre-existing global facts. Changed or missing required tuple facts require refusal/requalification; source policy, intended configuration and actual observations remain distinct.

## Unchanged limits, budget and acceptance

All original controls remain: cpu.max25000/100000 fair-class rate; memory.max268435456/swap0/oom.group1; pids32; one16MiB/512inode scratch; FSIZE8MiB/FD64/core0/RTPRIO0; original10s probe deadline, separate original2s stop confirmation and stdout/stderr65536 bytes each. No heartbeat, readiness, policy step or retry renews these windows.

The same fixed catalog uses at most24 admissions in its original600s qualification admission window. Host policy preparation/diagnostics are bounded technical setup, not extra hostile probes or an unbounded subprocess chain. Failed/unknown admissions are charged and retained; this new-VM qualification does not erase/refund either earlier run or retry inside an exhausted original window.

These fixed OS probes still consume zero research reservations and zero replay-engine calls. Original protocol/Job/family identities,5/8/11-slot fixtures, golden, PR94, committed-result ACK and unknown-slot semantics stay unchanged. No SDK/domain/store integration or research authority is created.

Only complete actual fixed-probe evidence may qualify this exact reference tuple. Audit truncation, startup refusal, missing facts and uncertain stop/cleanup remain explicit. Keep original owned-cgroup kill, deadline checks and exact-owned cleanup; no live scratch deletion, global prune, replacement of caller paths or automatic rerun is authorized.

Independent human security review remains NOT_PERFORMED; external-human reproduction remains0/0/PENDING. Reference success cannot enable product M1 or M2. This freeze authorizes no release, GPU, additional server, remote listener, auto-merge or external contact; all implementation/probe execution remains remote CPU only.

## Primary references

- [Ubuntu24.04 userns restrictions and named-unconfined exception](https://documentation.ubuntu.com/release-notes/24.04/); [Ubuntu AppArmor scope](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/).
- [aa_change_profile](https://manpages.ubuntu.com/manpages/noble/man2/aa_change_profile.2.html), [parser add/cache semantics](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html), [NNP/LSM semantics](https://docs.kernel.org/userspace-api/no_new_privs.html).
- [Upstream named-unconfined inheritance report](https://gitlab.com/apparmor/apparmor/-/issues/527): a reported behavior to verify, not certification of the selected GHA kernel.
