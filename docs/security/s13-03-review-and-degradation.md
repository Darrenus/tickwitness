# S13-03 independent review preparation and capability degradation

2026-11-27 Asia/Singapore. **Reviewer UNASSIGNED; independent human security
review NOT_PERFORMED.** This is a review preparation packet for
[S13-03 / #39](https://github.com/Darrenus/tickwitness/issues/39), not a completed
security assessment, new attack run or permission to enable a capability.
Product **M1 remains DISABLED**, with no SDK/CLI/Job admission integration;
M2 hosted or cross-user service remains unsupported.

Owner Darrenus accepted S13-02 and merged
[PR115](https://github.com/Darrenus/tickwitness/pull/115) normally at
2026-11-27T09:58:53Z (17:58:53 Asia/Singapore), actual merge
[`40aede39b4d7b051b00b0dd604738e736d3f4c25`](https://github.com/Darrenus/tickwitness/commit/40aede39b4d7b051b00b0dd604738e736d3f4c25).
The accepted candidate was
[`89e12eb3e2e371ea7a4939f277bab57cd3c7843e`](https://github.com/Darrenus/tickwitness/commit/89e12eb3e2e371ea7a4939f277bab57cd3c7843e).
That owner decision is separate from independent human security review. Earlier
pre-acceptance snapshots retain their original status and evidence.

## Review scope and evidence identities

Review the internal reference launcher, fixed synthetic catalog, bounded
controller and evidence transport against the
[execution trust model](../contracts/execution-trust-v1.md),
[reference contract](../contracts/restricted-reference-v1.md),
[EC2 specialization](../contracts/restricted-reference-ec2-v1.md),
[v3 contract](../contracts/restricted-reference-ec2-recovery-v3.md) /
[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md), and
[transport contract](../contracts/restricted-reference-ec2-transport-v1.md) /
[ADR0051](../adr/0051-ec2-evidence-receive-and-readback.md).
The privileged controller, selected dependencies, owner and kernel remain trusted.
Named-unconfined AppArmor authorizes the selected userns transition; it is not
additional MAC confinement. Finite reference evidence does not establish full
application/domain isolation, hostile-owner protection or arbitrary-source safety.

| Evidence | Identity and actual scope |
| --- | --- |
| Actual EC2 qualification | Source `908d56db32439f38686346687a5b43239b1b7264`; all 24 fixed controls PASS under the recorded tuple. Current 24 plus prior 21 = cumulative 45 technical admissions; pending/unconfirmed 0, poisoned=false; research reservations and replay invocations 0 |
| Historical transport recovery | Reader source `e9ff318efc9ea2c333dcb241d0871150c3d30446`; CLOSED 63-file readback, unchanged original 604-file audit, 558 original pins and ten source byte/hash bindings. Original handoff remains expired / controller 74 / ACK genuinely absent |
| Source regression | Accepted candidate `89e12eb3e2e371ea7a4939f277bab57cd3c7843e`: [Engineering 45968025293](https://github.com/Darrenus/tickwitness/actions/runs/45968025293), all 16 jobs SUCCESS; [transport 45968025488](https://github.com/Darrenus/tickwitness/actions/runs/45968025488), 91 PASS / 0 fail / 0 error / 0 skip; [Documentation 45968025303](https://github.com/Darrenus/tickwitness/actions/runs/45968025303), SUCCESS |
| Separate refusal | [Legacy GHA reference 45968025352](https://github.com/Darrenus/tickwitness/actions/runs/45968025352) remains FAILURE / REFUSED before policy commands or loading because attachment expressions were unknown; qualification SKIPPED. This is neither EC2 failure nor a waived green check |

The [public v3 evidence record](ec2-reference-recovery-v3-evidence-2026-11-27.md)
contains the catalog, tuple, outcome association and closed-audit anchors. The
accepted candidate, actual owner merge, qualification source and reader source
are distinct identities. Source CI is automated regression evidence; it is not
an independent human review, a new AWS qualification or a new live ACK success.
New documentation revisions require their own actual remote checks.

## T01–T10 evidence map and residual gaps

Control numbers below refer to the actual 24-control catalog in the public
record. Source-test links identify complementary regression coverage, not new
executions or additional independent reviewers. A mapped threat is not thereby
fully resolved for product M1.

| Threat | Existing scoped evidence | Question or gap retained for review |
| --- | --- | --- |
| T01 filesystem traversal, links and replacement | Actual 02 `filesystem`, 03 `readonly`; [safe-input tests](../../tests/infrastructure/test_safe_input.py) and [reader descriptor/ancestor/replacement tests](../../tests/test_ec2_reference_reader_v1.py) | Do the actual view and canaries support each claimed denial? Trusted roots, hostile owner/ancestor assumptions and product integration remain separate |
| T02 malicious source/dependency or parser abuse | Actual read-only TCB/source closure; 03 `readonly`, 05 `identity`, 20–22 namespace/syscall/ABI denials; [source registration](../../src/tickwitness/application/research.py) retains non-execution of submitted source | Which interpreter/dependency and parser assumptions are trusted? No arbitrary-source contract, supply-chain authentication or proof against every malicious dependency is supplied |
| T03 credentials, environment, sockets and egress | Actual 04 `environment`, 06–10 IPv4/IPv6/DNS/loopback/inherited-FD controls and protected canaries | Are denial observations and offered canaries sufficient for this exact policy? Product M0 does not inherit the reference's network/environment isolation |
| T04 process, FD, output or detached expansion | Actual 12 `pids`, 15 `fds`, 18 `output_flood`, 19 `detached`; [assessor/member regressions](../../tests/test_restricted_reference_qualification.py) | Are host and guest members, sessions, signal behavior, stop and cleanup independently associated? No SDK/CLI/Job M1 lifecycle is integrated |
| T05 CPU, memory, writable bytes and inodes | Actual 11 `memory`, 13 `disk_bytes`, 14 `inodes`, 16 `file_size`, 17 `cpu`; actual controller values and counters | Do units and task scope match the claim? CPU bandwidth is not cumulative CPU time; private scratch is not a host-wide disk quota; physical kernel/IO completion is not guaranteed |
| T06 forged output or authoritative-state mutation | Actual 23 `malformed_output`, 24 `stdio_closed`; [assessor tests](../../tests/test_restricted_reference_qualification.py), [strict v3 report/manifest tests](../../tests/infrastructure/test_restricted_reference_ec2_recovery_v3.py) and [receiver tamper regressions](../../tests/test_ec2_reference_receiver_v1.py) | Reference qualification authority is bounded. It does not newly qualify hostile worker access to research ledgers, coordinator publication or the full domain state under M1 |
| T07 budget reset through retry, ACK or identity change | Actual retained 21+24=45 and consumed v3 authority; [v3 fences/history tests](../../tests/infrastructure/test_restricted_reference_ec2_recovery_v3.py), [original-slot followup tests](../../tests/infrastructure/test_job_followup_supervisor.py) and receiver permanent-intent/no-retransmission regressions | Technical admissions are not research attempts. Future isolation admission must still compose with the same original protocol/family/Job rules; no reset, refund, new namespace or implicit rerun is allowed |
| T08 unsafe cleanup, diagnostic loss or disclosure | Actual per-case stop/cleanup and protected-canary checks; unchanged pins/audits; [reader faults](../../tests/test_ec2_reference_reader_v1.py) and [owned Job cleanup regressions](../../tests/infrastructure/test_job_control_supervisor.py) | Uncertain stop or ownership retains diagnostics. Original source inodes were not fully recorded; original producer fsync completion remains NOT_INDEPENDENTLY_OBSERVED. Neither is filled from later stable bytes |
| T09 hostile producer/owner rewrites all anchors | Explicit trust-model exclusion and consistency checks against retained anchors | No hostile-owner authentication result exists. A signature/trust-anchor design and its qualification would be separate work; hashes alone do not resolve this threat |
| T10 malicious Agent/tool instructions or cross-user service | [SDK parameter/unknown-field regressions](../../tests/test_sdk.py), typed [CLI](../../src/tickwitness/cli.py), no M1 mode selector, listener or tenant admission | These interface constraints do not prove prompt-injection containment. Treat external text as data; hosted identities, ownership and permissions remain unimplemented and unsupported |

## Independent reviewer handoff

The [working agreement](../planning/working-agreement.md) requires seeking
external review before opening untrusted-code capability. This packet prepares
that work; it sends no invitation and assigns no reviewer. AI review, owner merge
and CI do not satisfy the independent-human gate. Reviewer availability and
actual participant evidence are unresolved dependencies, so this packet alone
does not make the whole story Ready or Done.

The review should answer these scoped questions:

1. Are the trusted components, exact source/tuple and excluded adversaries clear,
   and do the actual namespace/mount/identity/FD/filter observations match them?
2. Does each positive or negative result bind its nonce, payload, host evidence,
   original clock, stop and cleanup, without promoting refusal/UNKNOWN to PASS?
3. Are controller privilege, policy transition, per-task limits and owned cleanup
   bounded, including detached descendants and evidence-preserving failure?
4. Are qualification, research accounting, publication authority and transport
   kept separate, including consumed allowances and no retransmission after an
   uncertain ACK attempt?
5. Are the original expired/74 handoff, absent ACK, fsync uncertainty and missing
   original source-inode history retained honestly? New live AWS receiver/ACK
   success is still unproven; historical recovery is not that proof.
6. Does the degradation table below keep unsupported capability unavailable
   without suggesting that the current product contains an M1 execution path?

Owner and an actual reviewer must agree the scope and evidence access before any
transfer. Keep credentials, contacts, consent originals, raw host logs, private
machine paths and restricted market/strategy data in approved private storage.
Use approved read-only copies and the retained hashes to identify evidence;
record exactly which bytes the reviewer received or inspected. A hash or
pseudonym is not publication permission. Missing access stays UNKNOWN /
NEEDS_EVIDENCE; a public summary must not be described as a review of unseen raw
cases. Do not alter a CLOSED scope to add review notes; retain a separate dated
review record linked to its anchors.

No access arrangement here authorizes outreach, a cloud Start, a policy load,
probe, qualifier, exporter, old ACK, replacement receipt or broader runtime
access. Any separately proposed execution needs its own explicit scope and
existing budget/authority; this packet does not supply it. Project execution,
imports, tests, lint and builds remain remote CPU only. Static inspection of
this document is not an attack test.

## Manual review and finding record prompts

These prompts describe human notes, not a domain/persistent artifact schema,
SDK type, executable validator or automatic approval mechanism. No review or
finding is populated by providing the format. Leave unobserved values UNKNOWN;
an empty finding list must not be reported as zero vulnerabilities.

| Review record field | Required note |
| --- | --- |
| Review ID / date / timezone | An actual separate record and when the work occurred |
| Reviewer / independence / conflicts | Actual human and relevant experience; relationship to implementation/owner and any limits on independence; public identity only with permission |
| Agreed scope | Accepted candidate, actual merge and exact reviewed source revisions; relevant T01–T10 IDs, components and explicit exclusions |
| Evidence access | Approved private references, hashes, access dates and exactly what was inspected; unavailable records and limitations |
| Method and attribution | Static review, review of retained actual evidence, or separately authorized remote execution; identify human, AI and automation contributions separately |
| Outcome and limits | NOT_PERFORMED / IN_PROGRESS / NEEDS_EVIDENCE / COMPLETED as actually supported; findings references, unresolved questions and human conclusion, with no automatic enablement |

| Finding record field | Required note |
| --- | --- |
| Finding ID / threat / affected revision | Stable reference, T01–T10 mapping and exact affected component/source |
| Observation and expected behavior | Concrete discrepancy, attack preconditions, trust scope and affected asset |
| Evidence class and references | Retained actual host result, source regression, static reasoning or untested hypothesis; approved raw references/hash anchors and reproducibility limits |
| Severity and uncertainty | Apply the working agreement's P0–P3 meanings with a reason; record uncertainty instead of inventing exploitability or a clean result |
| Immediate degradation | Capability kept disabled/refused, diagnostics retained and whether an existing supported M0 route remains appropriate for trusted code |
| Follow-up and authority | Proposed change or additional evidence; owner/assignee and separately needed execution authorization; preserve original slots/deadlines/committed results |
| Disposition and verification | OPEN / NEEDS_EVIDENCE / FIXED_PENDING_VERIFICATION / VERIFIED / ACCEPTED_LIMITATION with actual decision-maker/date/evidence; preserve prior entries and disagreement |

Owner disposition is not independent re-verification. A reviewer completion
record does not itself enable product M1, open a listener, release a version or
prove external adoption. Security reports follow [SECURITY](../../SECURITY.md).

## Default-disabled and degradation decisions

This table states review/admission policy under the existing contracts. It adds
no runtime mode selector or new implemented state machine.

| Trigger | Required decision and retained evidence |
| --- | --- |
| Human review missing or scope insufficient | Keep M1 DISABLED and arbitrary-source capability unavailable. Record reviewer UNASSIGNED / review NOT_PERFORMED or the actual later limitation; retain ordinary M0 support only for its existing trusted built-in scope |
| Missing or changed required tuple/control proof | Do not inherit a previous reference PASS or silently run untrusted code as M0. Keep the requested isolation unavailable; record REFUSED / UNKNOWN / NOT_QUALIFIED as applicable. This is no permission to requalify a new tuple |
| Uncertain stop, live membership or replaced owned paths | Stop further admission under the applicable contract, preserve scratch/originals/diagnostics and charged state; do not force/lazy-delete or signal an unrelated reused identity |
| Malformed, stale, forged or incomplete evidence | Refuse promotion to qualified/successful output or a research finding; preserve raw failure and its source. Missing bytes, exit 0 or EOF cannot fill a proof gap |
| Exhausted, consumed or uncertain allowance | Preserve original protocol/Job/family identities and all charges; no renamed run, refund, hidden retry, restored clock or committed-result re-execution. Existing ACK-only research recovery remains within its original contract |
| Original failed handoff or unproven new live receiver | Keep expired/74 with genuinely absent ACK and the separate successful historical readback. No old ACK/export/qualifier replay. Do not describe synthetic receiver regressions as successful live AWS transport |
| Arbitrary source, hosted/tenant admission or a new listener requested | Remain unsupported and expose no such capability. Registration, scalar parameters, container placement or owner acceptance do not grant execution/tenant authority |
| Private evidence cannot be shared or verified | Record the access limitation and NEEDS_EVIDENCE; narrow the conclusion and keep the dependent capability unavailable. Do not upload restricted originals to make a public checklist appear complete |

## Review scenarios — not newly executed tests

The following are paper-review cases for evaluating this packet. They are not
new host probes, test results, participant cases or permission to run commands.

| Case | Inputs to inspect | Expected review conclusion |
| --- | --- | --- |
| Positive | An authorized existing M0 built-in workflow and its original budget; the exact recorded EC2 catalog/source/tuple and retained evidence | M0 keeps its existing support. The reviewer can trace the narrow reference PASS and accounting without enabling M1 or attributing human review to CI |
| Negative | A request to treat registered Python, an `execution_ready` scalar, another host or an old ACK retry as permission for isolated execution | No new authority is created. M1/arbitrary-source/hosted execution stays unavailable; no silent fallback, rerun, new allowance or rewritten old handoff |
| Unknown | Missing raw evidence/reviewer/stop fact, original fsync completion not independently observed, or no verified activation date | Record the specific UNKNOWN / NEEDS_EVIDENCE and dependent gate. Do not infer safe isolation, a received ACK, a human assessment or a reuse window |

## Delivery and remaining dependencies

The original S13-03 estimate remains **8h** within S13's **10+16+8=34h** and
unchanged quality capacity. Plan at most **6h preparation + 2h conditional
response** to actual reviewer/intake findings; these are planned allocations,
not measured hours or a promise that an external review will arrive or fit.

This preparation can be reviewed for traceable scope, evidence mapping, explicit
unknowns, private-access handling and default-disabled decisions. Its own remote
documentation checks and owner acceptance must be recorded after they occur.
Neither preparing the prompts nor checking their links completes the human gate.

The separate [S13-03 adoption observation](../planning/s13-03-adoption-observation-2026-11-27.md)
and [onboarding evidence contract](../contracts/onboarding-evidence-v1.md) retain
actual verified counts and windows. External-human reproduction remains
**0 attempts / 0 successes / PENDING**; no participant, activation or observation
start is invented here. Security preparation cannot substitute for real adoption.
Reviewer availability, actual review and participant-dependent evidence remain
unresolved; do not mark the entire story Ready/Done from this packet alone.
