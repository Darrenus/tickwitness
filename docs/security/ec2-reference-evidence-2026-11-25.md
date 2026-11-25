# First dedicated EC2 qualification — 2026-11-25

Result: **NOT_QUALIFIED**. Product M1 remains **DISABLED**, PR115 remains Draft,
and S13-02 / #38 is not complete. The fixed positive control failed before the
guest observation gate; the remaining23 controls were not admitted. This is a
failed qualification, not successful isolation-negative evidence.

## Executed source and bounded evidence

The actual EC2 source was
`ae3d8e7981a79d6fc692f2cb656534a2f9a6683b`, following the separately pushed
[EC2 contract](../contracts/restricted-reference-ec2-v1.md) / ADR0047 freeze.
Its preceding source Engineering run45626224529 completed all16 jobs successfully;
Documentation run45626224572 also passed. The legacy GHA reference refusal is
separate and remains NOT_QUALIFIED. Source CI did not grant EC2 isolation status.

The operator started the existing selected instance at22:51:29 Asia/Singapore.
Pinned SSH identity, Ubuntu24.04.5/x86_64, actual kernel7.0.0-1018-aws, active and
enabled4h boot deadline, fresh host/run/source records, script hashes and remote
shell syntax were checked before launch. The reviewed batch ran through the
existing detached systemd lifecycle launcher. No new server, credential, IAM
role, security-group rule, listener or GPU was introduced.

Trusted dependency preparation and the exact Git/source-lock checks succeeded.
Both global userns controls were1 before and after preparation. The three bounded
policy commands returned0; the frozen83-byte named manual-attachment policy was
loaded. The bootstrap independently reported the selected AppArmor label,
UID/GID61184, empty supplementary groups and NNP1. These observations establish
only the phases reached, not a qualified final guest.

The batch exported its persistent partial evidence before automatic Stop.
Exactly one matching BEGIN/END pair was captured; the decoded archive contains
168024 bytes with SHA256
`4203ef17dff24fe38cd2107e93a1b764e8bfacc96e87172251dfe5630f48aba5`.
No export-uncertain marker was present. Private raw host evidence stays outside
the public repository and does not modify sealed historical PR114/PR115 archives.

## Observed failure and accounting

The positive control's Python interpreter exited2 with:

```text
can't open file '/input/payload.py': [Errno 13] Permission denied
```

The launcher process started; the fixed guest payload did not reach its
independently observed gate. Its result records `setup_refused`, confirmed stop,
confirmed cleanup, no remaining cgroup members, and unchanged protected canaries.
The controller ended the run instead of attempting the remaining catalog.

| Durable observation | Actual value |
| --- | --- |
| Original qualification ceiling | 24 admissions / 600s; setup30s; admitted case10s |
| Charged / backend accepted | 1 / 1; no refund |
| Pending outcomes / backend ACK uncertainty | 0 / 0 |
| Observed guest payload starts | 0 |
| Remaining controls | 23 not admitted; UNKNOWN, not PASS |
| Durable phase / outcome | TERMINAL / NOT_QUALIFIED; poisoned=true |
| Final success hash / terminal receipt | null / null; no qualification acceptance |
| Research reservations / replay engine calls | 0 / 0 |

The archived host claim and run claim are byte-identical. Claim, state, case,
provider, manifest and report bind the same original run/source/boot. The actual
case result SHA256
`dd5fb4e40f9b88fb2926808fb7a3e82f6720a356ea196dc5cebbfa8eb0a1450b`
matches both the report reference and the durable admission outcome. The actual
manifest SHA256 is
`26d2ad9302ee778939fd5e676e87746fcbdf77ed7823f88d63afebfd58cb3c9e`.
The failure report exists, but it is not a success receipt: the frozen failed-run
path leaves the success hash unset and cannot authorize qualification.

Fresh AWS control-plane readback after the batch showed **Stopped**, no public
IPv4 address, and `Client.InstanceInitiatedShutdown`. SSH disconnection alone
was not used as shutdown acceptance. Retained EBS remains billable.

## Diagnosis and next gate

The trusted batch intentionally keeps umask077. The case input directory was
created with `mkdir(mode=0755)` without an explicit final chmod, so that umask
removes the guest's directory-search permission. Input files already receive an
explicit0644 mode. The narrow source correction must set0755 on only the fresh,
exclusively created input directory, preserving root ownership, the private
controller umask, read-only guest bind and all other controls. Remote regressions
must exercise the actual input-preparation path under umask077 and reject existing
or symlink paths without modifying foreign modes or bytes.

This diagnosis and a source regression do not repair or reopen the recorded run.
Its charge, original clocks, terminal poison, source anchor and partial evidence
remain intact. There was no automatic second invocation, fresh nonce, claim
deletion, policy unload or budget reset. Any later host recovery / qualification
attempt needs a separately reviewed plan under the frozen recovery refusal;
source edits alone grant no retry authority.

Original protocol/Job/family budgets, identities and5/8/11 fixtures are unchanged;
committed results remain verification/ACK only. Independent human security review
is **NOT_PERFORMED**. External-human research reproduction remains
**0 attempts / 0 successes / PENDING**; neither this run nor CI is a human attempt.
