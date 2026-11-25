# Dedicated EC2 reference qualification v1

S13-02 continuation contract, 2026-11-25 Asia/Singapore. This contract and
[ADR0047](../adr/0047-dedicated-ec2-reference-admission.md) require independent
review, an actual commit/push and remote-ref readback before their loader/provider
implementation or any qualification payload. Selection, a provisioned VM and lifecycle smoke
checks are not a qualification result. Product M1 remains **DISABLED**, M2 is
unsupported, independent security review is **NOT_PERFORMED**, and external-human
research reproduction remains **0 attempts / 0 successes / PENDING**.

This is a separate specialization of [Restricted reference v1](restricted-reference-v1.md)
and [Execution trust v1](execution-trust-v1.md). It neither rewrites the GHA-only
[AppArmor v1](restricted-reference-apparmor-v1.md) selection nor changes its opaque
attachment refusal or historical NOT_QUALIFIED records. Original S13-02 capacity
stays16h; S13 stays10+16+8=34h and the ongoing-quality capacity is unchanged.

## Scope and order

Only the existing dedicated-use EC2 CPU VM below is selected. It is an owner-trusted
single-host reference, not a physically exclusive host, independent hardware
attestation, hosted tenant boundary, arbitrary-source runner, SDK/CLI execution mode,
Job/Catalog schema change, listener or research finding. The root controller and
its approved dependencies remain trusted; the closed synthetic probe catalog is
the adversarial workload. No project or probe executes on the owner's workstation.

1. Complete remote automatic-stop exceptional-path verification before advancing
   this reference. A stopped VM or an SSH disconnect alone does not certify the
   test outcome or the guest controls.
2. Read-only host inventory may precede implementation. Freeze this provider,
   manual policy, identity schema and limits before changing/loading policy or
   running probes. Read back the actual pushed freeze revision.
3. Implement and review the new guarded provider and receipts; preserve the old
   GHA v1 guard and parser. Never supply invented GITHUB_* fields to pass that guard.
4. Bind actual package/TCB/policy bytes and pre-load host observations before the
   one policy add; bind the final canonical manifest and SHA before any payload.
5. Run the original fixed catalog once under its one original qualification
   budget. Preserve partial/unknown results and confirm owned stop/cleanup.
6. Persist bounded evidence and request instance Stop. Independently observe the
   AWS control-plane Stopped state; do not infer it from a client exit.

Missing dependencies or cgroup controllers may be prepared only by the trusted
host-provisioning phase, with declared changes and actual readbacks bound into the
pre-probe manifest. The qualifier never installs missing components, enables
global controllers or otherwise mutates global configuration while executing
probes; missing required controls at admission refuse execution. This preparation
does not authorize disabling AppArmor, relaxing userns restriction or widening
task privileges.

## Selected host and honest provider identity

| Owner-selected attribute | Required value |
| --- | --- |
| Provider | `aws_ec2_dedicated_v1` |
| Instance | `i-0d79530ca78320939` |
| Region | `ap-southeast-1` |
| AMI | `ami-09289bc217ad5e9e7` |
| Instance type | `m7i.2xlarge`, nominal8vCPU/32GiB; not the task's resource allocation |
| OS/architecture | Ubuntu24.04, Linux x86_64; actual release/kernel/runtime required |

The earlier lifecycle inspection observed kernel `7.0.0-1018-aws`. That is a prior
observation, not a future pin or a qualification. Observe the exact current tuple,
boot ID, package versions, binary/source digests, cgroup/mount state and relevant
host controls afresh. Stop/Start changes boot identity and may change public IP;
neither an IP address nor the instance name substitutes for instance identity.

Use a separate versioned provider record, `restricted_reference_ec2_host_v1`,
with `schema_version=1`. The required identity fields are:

| Field | Binding and authority |
| --- | --- |
| `provider` | Exactly `aws_ec2_dedicated_v1`; no arbitrary remote-provider string |
| `expected_identity` | The selected instance ID, region, image ID, instance type and x86_64 architecture above |
| `observed_identity` | Those actual fields from the bounded raw EC2 instance identity document; retain raw byte count/SHA256 and provenance |
| `source_revision` | Actual40-lowercase-hex source commit, bound to the transferred source/TCB bytes, not a branch label or caller-invented environment value |
| `run_id` | One root-recorded32-lowercase-hex qualification identity, stable across policy setup, manifest, admissions and publication |
| `boot_id` | Actual kernel boot UUID, observed before setup and rechecked before admissions |
| `host` | Actual OS/kernel/architecture, controller identity, namespaces, mounts and the existing reference tuple fields |
| `gha_metadata` | Explicitly null with an AWS-not-GHA reason; no fabricated ImageOS/ImageVersion, workflow run or attempt |

Required fields are checked with exact types; unknown provider-record fields or
schema versions cannot silently add authority. Retain other bounded raw IID fields
as observations without treating them as new admission controls. Mismatch, absent
required metadata, stale boot/source/run identity or unbound source bytes refuses
admission. The provider record is host evidence, not an authenticated historical
ledger, producer signature or defense against its owner/kernel rewriting anchors.

The trusted root controller retrieves only the fixed IMDSv2 token endpoint and
`/latest/dynamic/instance-identity/document` on `169.254.169.254`. Use one token PUT
(TTL60s) and one document GET, no redirects/proxies or IMDSv1 fallback, at most5s
combined under the original setup deadline; cap token4096B and IID16384B. No
credential metadata is requested. Never persist/print the token or pass it, its
socket or other host FDs/environment into the child. This host-only setup access
does not grant any guest network route. Failure is explicit, not retried invisibly.
Cache the bounded raw IID bytes in exclusively created root-owned setup evidence
and bind their identity/digest. Subsequent per-probe tuple checks revalidate that
cache, provider-source digest and actual boot/source/run identity; they do not
perform another metadata request or obtain a fresh network timeout. The selected
provider module and receipt validator are part of the frozen source/TCB closure.

## Manual-only AppArmor policy

The exact selected UTF-8 bytes, LF-terminated including the final newline, are:

```text
abi <abi/4.0>,

profile tickwitness-reference-ec2 flags=(unconfined) {
  userns,
}
```

Their SHA256 is `62c319e3655d13e4c4f856e3591efb48dda36ce3ba175681688ff49b05592314`.
The name is not an absolute path; there is **no exec attachment conditional**,
xattr condition, include, wildcard attachment, capability or additional transition
rule. This is explicit userns authorization, not enforce-mode MAC confinement.
Descendants can inherit its label; the controller remains outside that profile.

Stage only root-owned, non-symlink, single-link frozen bytes at
`/var/lib/tickwitness-reference-ec2/runs/<run_id>/policy.apparmor`, where `<run_id>`
is the explicitly selected32-hex identity. Common root ancestors, including the
dedicated root and `runs` directory, may already exist only after root ownership,
directory/non-symlink identity and absence of group/world write permissions are
verified. Newly needed common ancestors receive those same checks. The accepted
driver invocation exclusively creates its selected run directory, run record and
claim on first admission; its later policy stage and evidence files are also
exclusive first creations. Permanent older run/source/boot records remain
untouched. This stage is outside `/etc/apparmor.d` so ordinary
boot policy loading does not silently replay the one authorized add. Source file
identity, staged inode/owner/mode/digest, parser/config/ABI/library closure and
exact argv are captured before loading.

The loader uses one `apparmor_parser --add --skip-cache --base=/etc/apparmor.d`
invocation for that staged file; never replace/reload, reuse a same-name policy,
unload foreign policy, clear caches, change namespaces or globally reload a policy
directory. A pre-existing selected profile name or a selected claim/stage/evidence
from an earlier invocation refuses setup. The driver's verified own current claim
is handed to the loader in the ordered phase below; its expected existence does
not itself constitute earlier-run reuse. The one original30s setup window permits at most3 fixed
external commands (parser version, selected dpkg-query, one add), stdout/stderr
65536B each, no retry. IMDS reads are in-process trusted setup, not extra external
commands. Keep existing feature limits256 regular files/4096B each/1MiB total,
ABI/config65536B each and canonical pre-load/setup documents262144B each.

Foreign loaded profile names/modes and raw attachment introspection are captured
before/after; opaque attachments remain UNKNOWN, with their actual raw values.
Do not decode them speculatively, assert they cannot match bwrap, delete them or
retroactively convert the old v1 refusal into success. This new profile does not
register a competing executable attachment, so this scope makes no universal
attachment-conflict-closure claim. Missing/ambiguous selected-name absence or
unexpected changes to foreign observed state still refuse setup.

Require actual selected name/mode and manual-only introspection readback. A kernel
may expose the non-absolute selected name as its attach fallback; retain that raw
value and its schema-defined interpretation, never relabel it as `/usr/bin/bwrap`
or an observed global absence of foreign matches. An opaque selected attachment,
absolute/wildcard conditional or an unexpected selected mode is not accepted.
Keep AppArmor enabled and `apparmor_restrict_unprivileged_userns=1` unchanged.

After the gated root bootstrap is attached to and independently verified in its
owned cgroup, and before UID/groups drop and NNP, call the bound libapparmor
`aa_change_profile("tickwitness-reference-ec2")`. Require raw pre/post labels,
return/errno and library/source bindings, plus independent controller observation
of that same child. Then retain original UID/GID61184, empty groups, irreversible
drop, NNP=1, zero retained host caps, fair scheduler, required namespaces, bwrap
cap-drop/clearenv/FD closure, read-only view and final seccomp.

The exact expected bootstrap and guest label is
`tickwitness-reference-ec2 (unconfined)`. Both host-observed gates must match before
GO, with every existing UID/NNP/capability/namespace/mount/FD/filter/controller
proof. Named policy load or bootstrap self-report is insufficient. A foreign
automatic transition, lost label, incompatible kernel or missing proof refuses
execution; never remove NNP, grant capabilities, change global AppArmor/sysctls,
use optional namespace flags or fall back to M0 to obtain a pass.

## Persistent-host freshness and shared budgets

A persistent VM is not a fresh GHA runner after reboot. The accepted driver first
validates the secure common root ancestors, then exclusively claims a root-owned
host admission and first-creates its selected run directory, run record and claim
under `/var/lib/tickwitness-reference-ec2/runs/<run_id>`. Bind the live owner
invocation identity/ownership, provider/instance/source/run/boot, lifecycle phase,
original monotonic anchors and durable submitted/uncertain admission counters.
Reject simultaneous controllers, an unresolved foreign host admission, or a
selected claim/run/stage/evidence belonging to any earlier invocation. Do not
overwrite, silently resume or erase them; all older run/source/boot records remain
permanent. After boot change, the old run is ended/uncertain and cannot be resumed
by converting monotonic timestamps or starting a new600s window.

The same accepted invocation hands its verified own claim through the driver,
loader and backend in the single ordered sequence
`CLAIMED -> POLICY_READY -> QUALIFYING -> TERMINAL`. The loader may join that
driver-owned `CLAIMED` record for its first setup, exclusively create its stage
and evidence, and advance only after the required policy readbacks. The first
backend may join that same `POLICY_READY` claim to enter qualification. At each
handoff, revalidate exact source/run/boot/owner-invocation binding and actual
claim ownership; a matching path, root UID or caller-supplied run ID alone is
insufficient. This handoff is not a second admission or earlier-run reuse. Failure
or uncertain ownership ends/poisons the invocation and retains its state. Repeated
loader setup or a second runner initialization is refused, even with matching
identity; component construction and phase entry cannot recreate the claim or
reset its durable budget. Claim authority/FDs never cross into the probe payload.

One accepted qualification invocation writes its600s monotonic admission anchor
once in its existing owned run record, before manifest/runner setup. Loader,
driver and backend share that same original durable budget; no component writes
fresh zero counters over an existing value. Every probe uses that same deadline, at most24
fixed submissions total; constructor recreation, retries, new nonces, cancellation,
SSH loss, Stop/Start or a different output directory cannot grant a second window.
The separately bounded30s policy preparation never renews probe deadlines or
creates another qualification invocation. New-run recovery or a subsequent loaded
policy/source selection requires an explicit new reviewed plan and retained old
records; no automatic replacement VM/profile/ledger or background restart loop.

All original per-task numbers and controls remain, without any host-size scaling:

| Control | Unchanged value |
| --- | --- |
| CPU | `cpu.max=25000 100000`, fair-class bandwidth rate, not cumulative CPU time |
| Memory | `memory.max=268435456`, swap0, oom.group1 |
| Processes | `pids.max=32`, including bootstrap/bwrap/task descendants |
| Writable scratch | One16MiB/512inode tmpfs, `/tmp` and `/dev/shm` aliases of it |
| File/FD/core/RT | FSIZE8388608, NOFILE64, CORE0, RTPRIO0; hard=soft ceilings |
| Probe time | Original10s monotonic admission, including its setup/start; separate2s stop confirmation |
| Output | stdout/stderr65536B each, bounded while pumping |

The root controller stays outside the task cgroup. Preserve required explicit
user/pid/ipc/net/uts/cgroup and mount isolation, native-x86_64 final BPF/ABI checks,
the same24 fixed cases and T01–T08 host-canary/independent-observation matrix from
the original contract. A nonzero exit, startup refusal, skipped case, lost host
observation or uncertain stop is not a passed negative case. Confirm complete
owned cgroup absence before exact-owned scratch/leaf cleanup; retain uncertain
resources/diagnostics and stop admissions, with no force/lazy unmount or broad prune.

Technical qualification consumes **zero research reservations and zero replay
calls**. It neither opens Job/Catalog/ledger state nor creates findings. Original
protocol/Job/family identities,5/8/11 fixtures, attempts/events/native wall limits,
golden and PR94 evidence remain unchanged. Actual research reruns require a new
slot from that same original protocol budget; committed results remain verify/ACK
only, and failed/unknown reservations are not refunded. Lifecycle acceptance is
separate operational testing, not a new research or hostile-probe allowance.

## Stop, evidence and enablement

Tests run only on the authorized remote CPU host. The separately verified lifecycle
service saves bounded results and requests Stop after success/failure/cancellation;
the per-boot four-hour fallback is not a replacement for10s/2s/600s controls or an
absolute AWS charge cap. Timeouts, setup failure, lost connection and incomplete
publication remain explicit. Confirm final Stop through the control plane; a Stop
request, shell exit or loss of SSH alone is insufficient. Stop retains billed EBS.

Reports bind the actual freeze and implementation commits, pre-load/final manifest
bytes/digests, provider/run/boot identities, original budget/accounting, fixed
nonce/case/source identities, independent observations, raw bounded outcomes,
stop/cleanup and unresolved gaps. Archive each new attempt in a fresh sibling
scope; never write into sealed PR114/PR115 evidence or backfill a missing fact.

Only a complete actual pass can yield `QUALIFIED_REFERENCE_ONLY` for this exact
tuple. Production M1 stays DISABLED until its original integration/admission and
independent-security gates are separately satisfied; no arbitrary strategies, M2,
release, HTTP/MCP, GPU, extra server, auto-merge or external contact is authorized
by a reference pass. External-human reproduction stays PENDING and distinct from
AI review, CI, owner acceptance and independent security review.

## Primary references

- [AWS instance identity document fields](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-identity-documents.html)
  and [IMDSv2 semantics](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html).
- [Ubuntu24.04 AppArmor profile heads](https://manpages.ubuntu.com/manpages/noble/man5/apparmor.d.5.html):
  non-absolute name, no conditionals and explicit named transition semantics.
- [aa_change_profile](https://manpages.ubuntu.com/manpages/noble/man2/aa_change_profile.2.html),
  [parser add/cache semantics](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html)
  and [NNP/LSM limits](https://docs.kernel.org/userspace-api/no_new_privs.html).
- [Upstream Linux v7.0 attach introspection](https://github.com/torvalds/linux/blob/v7.0/security/apparmor/apparmorfs.c):
  possible name fallback, not certification of the selected Ubuntu AWS kernel.
- [Original bounded reference controls and primary mechanism references](restricted-reference-v1.md).
