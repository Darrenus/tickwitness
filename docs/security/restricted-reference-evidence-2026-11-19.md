# S13-02 remote reference evidence and remaining gate

Date: 2026-11-19 Asia/Singapore. **Reference NOT_QUALIFIED; PR115 remains Draft; product M1 DISABLED; M2 unsupported.** This records actual remote observations, separate from source regression and owner acceptance. It is not a security certification or an external-human review.

## Selection and implementation order

The [reference contract](../contracts/restricted-reference-v1.md) and [ADR0045](../adr/0045-restricted-reference-qualification.md) were actually pushed in commit [`5fc3377`](https://github.com/Darrenus/tickwitness/commit/5fc3377834831a00e4a4929d9f3196c3621912ad) before the initial adapter/probe implementation. They select dedicated GitHub-hosted Ubuntu24.04/Linux x86_64 CPU, required bubblewrap namespaces, host UID/GID61184, NNP, cgroupv2 controllers, final seccomp and one quota-bound tmpfs. The rolling label is not an exact image pin.

After actual userns refusal, the exact [AppArmor policy](../../research/security/reference-bwrap.apparmor), [compatibility contract](../contracts/restricted-reference-apparmor-v1.md) and [ADR0046](../adr/0046-explicit-reference-userns-authorization.md) were separately pushed in `0860658` and `aceda2c` before loader/transition code. Named-unconfined is a userns authorization exception, not additional MAC confinement; attachment is not limited to the reserved UID or setup instant. Global restriction1 and all original limits remain required.

The implementation candidate includes a trusted host controller, standalone gated bootstrap, fixed probe catalog, policy setup, bounded refusal diagnostics and pure decision regressions. It does not replace an existing Job launcher, open research stores, admit arbitrary source, or add a SDK/CLI mode. Missing environment proof refuses execution.

## Actual run history

| Run / source head | Actual outcome | Scope and missing evidence |
| --- | --- | --- |
| [44536018240](https://github.com/Darrenus/tickwitness/actions/runs/44536018240) / `e575a914` | NOT_QUALIFIED; bwrap loopback RTM_NEWADDR EPERM | One admitted backend launch, zero payload starts; 24 UNKNOWN results including23 unsubmitted. Stop/owned cleanup confirmed. No kernel audit on this original VM; do not retrofit a later cause |
| [44538107915](https://github.com/Darrenus/tickwitness/actions/runs/44538107915) / `56a4377` | NOT_QUALIFIED; separate-VM AppArmor denials observed | One admitted backend launch, zero payload starts. Three valid same-window audit records include userns_create and setpcap/net_admin denials. Collector overflow/malformed tail means audit completeness UNKNOWN; one child PID correlation lacks independent membership sampling |
| [44546661818](https://github.com/Darrenus/tickwitness/actions/runs/44546661818) / `663b5b8` | Policy preflight REFUSED | Kernel pseudo-file stat size was incorrectly treated as actual content length. No policy command/load; qualification step SKIPPED. No probe manifest or counters exist; subsequent code distinguishes only fixed kernel inputs from disk files |
| [44548411070](https://github.com/Darrenus/tickwitness/actions/runs/44548411070) / `8b9d8ff` | Policy preflight REFUSED: loaded attachment expression unknown | Actual124 loaded profiles:100 opaque attachments (91unconfined/5enforce/4complain),24 printable. Commands=[], load_submitted=false, retry_performed=false. Qualification step SKIPPED; no ReferenceRunner manifest, admission counter or payload-start record |

Observed earlier baseline was Ubuntu24.04.5, kernel7.0.0-1017-azure, ImageVersion20261111.370.1 and bubblewrap0.9.0/package0.9.0-1ubuntu0.3, binary SHA256 `e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71`. These observations do not certify later VMs or invent missing parser/ABI/library facts.

The `8b9d8ff` preflight independently read AppArmor enabledY, userns restriction1 and controller unconfined. Its saved loaded profile/attachment table cannot establish a complete non-conflict closure. No source filename, application name, package list or one winning exec label proves that an opaque loaded rule cannot also match bwrap.

The [upstream Linux attachment export](https://github.com/torvalds/linux/blob/master/security/apparmor/apparmorfs.c) can return `<unknown>` when a DFA exists without a printable attachment string. This explains why treating that value as an empty/nonmatching rule is invalid; upstream source is not a byte binding to this VM's running kernel. The implementation retains REFUSED rather than assuming a rule's meaning.

## What has not passed

The compatible policy has not actually loaded. The pre-NNP transition, guest identity/control observations and full T01–T08 attack matrix have not run under this compatibility candidate. Earlier startup/denial observations are not successful filesystem, network, exhaustion or detached-descendant probes. Pure decision tests, typing, packaging and ordinary CI success cannot supply those facts.

Local evidence archives preserve complete paginated API records, raw job logs, actual ZIP members, manifests/reports when they exist and the missing/partial facts. Their member hashes detect byte changes; they are not signatures or proof against a malicious producer. Failed heads and charged launches remain historical evidence, separate from later candidate checks.

## Next admission gate

Keep the current GHA reference unqualified. Select and freeze a fresh dedicated remote environment whose loaded executable-attachment closure is fully observable or actually empty, then capture its actual tuple and rerun the same fixed qualification with its original limits. Do not blindly retry identical unknown hosts, unload host policies to manufacture an empty set, remove NNP, disable AppArmor/sysctls, skip opaque rules, or silently adopt a new DFA decoder/policy namespace. A new mechanism needs a separate contract and review before implementation.

No product entry opens on reference success alone: lifecycle/Job integration and independent security review remain separate gates. Issue38 stays OPEN/in-progress; no owner acceptance or completed S13-02 delivery is claimed.

Original S13-02 capacity16h, total10+16+8=34h and quality capacity are unchanged, with no actual-hours claim. These fixed OS probes reserve zero research slots and invoke zero market replay engines; missing qualification counters are not fabricated as zero. Original protocol/Job/family budgets,5/8/11 fixtures, golden, PR94 and committed-result ACK semantics are unchanged. The two earlier charged launches are not refunded. Independent human security review is NOT_PERFORMED; external-human research reproduction remains0 attempts/0 successes/PENDING, #24 OPEN. All project execution remains remote CPU; no release, auto-merge, GPU, new server, listener or external contact occurs.
