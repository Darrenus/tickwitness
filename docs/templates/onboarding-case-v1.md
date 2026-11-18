# Own-case onboarding record — EMPTY_TEMPLATE

**EMPTY_TEMPLATE. No participant, attempt, activation or reuse event is recorded here. Do not include this file in live counts.** This is a manual note format under the frozen [onboarding evidence contract](../contracts/onboarding-evidence-v1.md) and [ADR0042](../adr/0042-manual-own-case-onboarding-evidence.md), not a research artifact, identity credential or executable schema.

Use the [operator guide](../user-onboarding.md) before intake and the [review examples](onboarding-review-examples.md) when reviewing a return. The [recruitment-gap snapshot](../planning/s12-02-recruitment-gap.md) records the current absence of verified own-case evidence separately. Existing [adoption definitions](../product/discovery-and-adoption.md#6-采用漏斗与指标字典) remain authoritative.

## How to use this blank record

Copy this template only when there is an actual case to record. Keep private originals, consent, contact details, commands containing secrets and restricted inputs in owner-controlled private storage. Record a safe reference here only with permission. A hash or pseudonym does not grant permission to publish. No account, telemetry or public raw-data upload is required.

The fields below are blank prompts, not example people or attempts. `UNKNOWN` means evidence is absent; `null` means no value has been recorded. Neither means zero, false, refusal, failure or permission. Use `NOT_APPLICABLE` only with a reason. Explicitly record a measured zero, if one is actually known, with its source. Never replace a missing duration or count with zero.

When creating a real copy, mark its record kind `OBSERVED_RECORD`, assign opaque private-safe identifiers, and fill only observed or clearly attributed self-reported facts. Append corrections; retain the earlier entry, raw failures and uncertainty. Review examples are fictional and must never be copied into a real case as evidence.

## 1. Record envelope

| Field | Blank value |
| --- | --- |
| Record kind | EMPTY_TEMPLATE |
| Process contract | onboarding-evidence-v1; manual notes only |
| Record ID / case ID | null / null |
| Pseudonymous participant ID | null |
| Record created at / timezone | UNKNOWN / UNKNOWN |
| Record author and role | UNKNOWN |
| Evidence observed as of / timezone | UNKNOWN / UNKNOWN |
| Private originals index / approved public summary reference | null / null |
| Visibility, retention and deletion arrangement | UNKNOWN |
| Previous record or correction reference | null |

Do not put a guessed identity, outreach event or participant into an empty slot. Repeated copies, environments and installations are not distinct people.

## 2. Intake, consent and actual participation

Record permission separately for each purpose. Absence of permission is not consent. A withdrawal changes future handling and follow-up; record the arrangement and any permitted retained evidence rather than silently rewriting history.

| Consent purpose | Status: UNKNOWN / GRANTED / DECLINED / WITHDRAWN | Scope, source and actual date |
| --- | --- | --- |
| Participate in the supported case | UNKNOWN | UNKNOWN |
| Keep private technical and assistance notes | UNKNOWN | UNKNOWN |
| Contact for case troubleshooting | UNKNOWN | UNKNOWN |
| Contact for the later reuse observation | UNKNOWN | UNKNOWN |
| Publish an anonymized summary | UNKNOWN | UNKNOWN |
| Publish participant quotations, with approved wording | UNKNOWN | UNKNOWN |
| Publish particular logs or technical artifacts | UNKNOWN | UNKNOWN |
| Redistribute particular input data | UNKNOWN | UNKNOWN |

Permission to participate does not imply permission to publish, quote, redistribute input or contact again. If a required permission is missing, record the paused or refused step and reason; do not execute merely to fill this record. This template does not authorize outreach.

| Participation field | Blank value |
| --- | --- |
| Self-reported role and exact source | UNKNOWN |
| Relationship to owner/maintainer, if known | UNKNOWN |
| Actual human operator and actions personally performed | UNKNOWN |
| Operation attribution evidence; private reference permitted | null |
| Human participation evidence; what it establishes and does not establish | UNKNOWN |
| Review state: UNREVIEWED / NEEDS_EVIDENCE / VERIFIED_EXTERNAL_HUMAN / MAINTAINER / AUTOMATION | UNREVIEWED |
| Human reviewer, review date and evidence references | UNKNOWN |

`external_user` in a return is a self-report. A successful command, SDK receipt, filename or environment matrix cannot authenticate a person. Owner, AI, CI and automation remain attributed to their actual roles. An external participant may receive help, but a proxy-operated case must not be described as the participant independently operating it.

### Operator/helper entry — repeat only for an actual actor

- Actor reference and role (participant / maintainer / other human / AI / automation): UNKNOWN.
- Who requested the work, who controlled execution and which actions they performed: UNKNOWN.
- Actual action dates/timezone and command, code-edit or review evidence: UNKNOWN.
- Self-reported versus directly observed attribution; reviewer and limits: UNKNOWN.
- Private evidence reference and approved publication scope: null / UNKNOWN.

## 3. Own research, lawful inputs and supported route

| Case field | Blank value |
| --- | --- |
| Participant's own research question and current workflow | UNKNOWN |
| Existing alternative/baseline and evidence reference | UNKNOWN |
| Declared constraints, scope and intended research decision | UNKNOWN |
| Why this is the participant's own case rather than an official example | UNKNOWN |
| Input source, acquisition/use rights and participant statement | UNKNOWN |
| Input redistribution/publication permission and evidence | UNKNOWN |
| Private input identity/hash, version, clock semantics and retained location | UNKNOWN |
| Supported route/profile and capability evidence | UNKNOWN |
| Fit: UNKNOWN / SUPPORTED / CAPABILITY_GAP / NOT_OWN_CASE | UNKNOWN |
| Unmet capability, unsafe input, unknown clocks or other refusal reason | UNKNOWN |
| Admission/stop decision, human reviewer, actual date and references | UNKNOWN |

Unknown input rights do not authorize distribution. Keep private data private. A support mismatch is intake evidence, not an activation or a demonstrated rejection of the product's value.

### Route and version pinning

- Route actually chosen: UNKNOWN. Separate SDK data preparation from an existing supported CLI research workflow.
- Source commit, package version, wheel/install artifact hashes and installation method: UNKNOWN.
- Python, OS/architecture, remote execution environment and optional engine/model versions: UNKNOWN.
- Provenance for each version/environment claim (observed output or participant report): UNKNOWN.
- Exact SDK program revision or CLI invocation reference; private original and any redactions: UNKNOWN.
- Input/model/configuration identities and supported execution/evidence contract references: UNKNOWN.

The current SDK v1 imports/inspects data, freezes/inspects **declaration-v1** and reads bounded development data. A capture summary or successful SDK program is technical integration evidence, not complete research evaluation. A declaration-v1 ID is not an **executable-v2** ID. There is no public SDK conversion or execution bridge; do not invent one for this case. A complete case must use a separately frozen, existing supported CLI workflow where required. Record a capability gap if the actual research is unsupported.

## 4. Original protocol and budget authority

Fill this before the first admitted execution; use `NOT_APPLICABLE` with the actual reason for an unexecuted/data-only route. Unknown budget state does not permit execution.

| Authority field | Blank value |
| --- | --- |
| Declaration-v1 reference, if actually created | null |
| Executable-v2 reference, if separately frozen | null |
| Original protocol, constraints and freeze evidence | UNKNOWN |
| Original total budget/limits and unit definitions | UNKNOWN |
| Original registry/ledger location and identity | UNKNOWN |
| Original authority verification: reviewer, date and evidence | UNKNOWN |
| Existing committed results to preserve and never rerun | UNKNOWN |
| Exhaustion/stop conditions and applicable resource limits | UNKNOWN |

Retries, reductions and search for this case share that same original protocol and ledger. An actual rerun needs an available original slot. Failed/interrupted reservations are not refunded; already committed results are not executed again. Do not reset a registry, rename/copy a protocol into an empty ledger, enlarge its frozen limits or substitute a fresh budget. Read the actual ledger evidence rather than guessing whether a particular refusal or installation failure reserved anything. Historical qualification and PR94 budgets are not this new case's spending authority.

## 5. Attempt entry — repeat only after an actual attempt or recorded stop

Keep installation failure, refusal, interruption and unknown terminal state. Do not create a result receipt for a step that never produced one.

| Attempt field | Blank value |
| --- | --- |
| Local note ID; link to this case | null |
| Actual attempt/run/job/result/evidence IDs, only when emitted | null |
| Actual operator/helper references and what each did | UNKNOWN |
| Start/end/timezone; observed versus estimated source | UNKNOWN |
| Route, environment/version pin and input/configuration references | UNKNOWN |
| Exact actual invocation or SDK program revision; private original | UNKNOWN |
| Planned but unexecuted steps and reason | UNKNOWN |
| Original protocol/ledger reference | UNKNOWN |
| Actual reservation identity, if emitted | null |
| Before/after capacity and authoritative ledger evidence | UNKNOWN |
| Actual process exit code; enclosing runner code separately | UNKNOWN |
| Raw stdout/stderr, logs, receipts and integrity references | null |
| Technical state: NOT_RUN / SUCCESS / FAILED / REFUSED / UNKNOWN | UNKNOWN |
| Terminal/result completeness and integrity evidence | UNKNOWN |
| Scope and eligibility of the research result | UNKNOWN |
| Failure/refusal/unknown reason and last observed state | UNKNOWN |
| Committed results preserved, cleanup state and next permitted action | UNKNOWN |
| Attempt recorder/reviewer, actual date and evidence references | UNKNOWN |

A command exit of zero does not settle research completeness, identity or adoption. A failed execution is not a budget-scoped not-found finding. A complete, properly scoped not-found or evidence-insufficient result may be valid only under its existing result contract; raw crashes and unfinished output are not promoted by renaming them. An SDK-only technical `SUCCESS` can correctly coexist with activation `PENDING`.

## 6. Assistance and time entry — repeat for actual work

Declare the limited-help criterion before evaluating assistance, referring to the [existing adoption plan](../product/discovery-and-adoption.md). Do not add a new numerical threshold to make this case pass. Record bespoke customization, proxy operation and ongoing maintenance even when technically successful.

- Criterion selected before assessment, source and declaration date: UNKNOWN.
- Help session reference, actual date, actor and role (human / AI / automation): UNKNOWN.
- Help requested, troubleshooting advice, commands operated, changes made and resulting participant action: UNKNOWN.
- Session count and source; unknown is not zero: UNKNOWN.
- Participant active time, unit and provenance: UNKNOWN.
- Maintainer/helper active time, unit and provenance: UNKNOWN.
- Compute/network waiting time, unit and provenance: UNKNOWN.
- Provenance independently for each duration: UNKNOWN (measured / participant-estimated / helper-estimated / UNKNOWN).
- Measurement or estimation method, evidence and overlap between intervals: UNKNOWN.
- Participant-operated versus proxy-operated work; further bespoke maintenance required: UNKNOWN.
- Human assessment against the predeclared criterion, reviewer and evidence: UNKNOWN.

Do not infer active effort from total wall time, silently sum overlapping work or convert waiting time into participant effort. The presence of AI help is recorded rather than hidden or treated as proof that a human operated the workflow.

## 7. Result, research decision and independent reproduction

| Result/decision field | Blank value |
| --- | --- |
| Complete supported result and bounded conclusion, or why absent | UNKNOWN |
| Original protocol/result/evidence references and integrity/completeness review | UNKNOWN |
| Participant's actual decision and reason, in approved words or attributed summary | UNKNOWN |
| Decision state: UNKNOWN / PARTICIPANT_CONFIRMED | UNKNOWN |
| Participant confirmation source, actual date and publication permission | UNKNOWN |
| Maintainer interpretation, kept separate from participant statement | UNKNOWN |
| Independent reproduction: actual operator, method, date and references | UNKNOWN |
| Reproduction result, scope, uncertainty and independence assessment | UNKNOWN |
| Value-realization assessment, human reviewer/date and missing evidence | UNKNOWN |

A confirmed decision may be to continue, correct, collect more evidence, stop or make no change; record its real reason. Software-generated advice, a maintainer's guess and future intentions are not participant decisions. Activation does not by itself prove value realization: that separately requires independent reproduction **and** a participant-confirmed research decision. A reproduction attempt is also not automatically PR94 acceptance, activation or reuse.

## 8. Manual activation review

Review dimensions separately. No field in this document grants executable authority or updates a counter. A real external human's failed/refused attempt can remain useful evidence without activation.

| Review dimension | State and actual evidence |
| --- | --- |
| Participation and actual operation attribution | UNREVIEWED |
| Consent and permitted evidence handling | UNKNOWN |
| Own lawful research and supported fit | UNKNOWN |
| Existing baseline and declared constraints | UNKNOWN |
| Valid complete, scoped research result | UNKNOWN |
| Assistance assessment under the predeclared criterion | UNKNOWN |
| Activation review: PENDING / ELIGIBLE / NOT_ELIGIBLE | PENDING |
| Human reviewer, actual review date and rationale/refs | UNKNOWN |
| Actual activation date, timezone and evidentiary basis, if eligible | UNKNOWN |
| Missing evidence, correction needed or ineligibility reason | UNKNOWN |

Keep `PENDING`/`NEEDS_EVIDENCE` when required facts are absent. `ELIGIBLE` requires reviewed real external participation, the participant's own research, baseline, declared constraints and a valid complete result. Official examples, owner/CI/AI proxy work, role-only assertions and SDK data/declaration/read success do not establish activation. Record the research decision and independent reproduction separately; do not invent them to complete the funnel.

## 9. Reuse observation — begin only from real reviewed activation

| Observation field | Blank value |
| --- | --- |
| Reviewed activation reference and actual activation date/timezone | UNKNOWN |
| Participant consent to follow-up and any withdrawal | UNKNOWN |
| 30-day window start/end; actual calculation basis | UNKNOWN |
| Observation as of / timezone and evidence | UNKNOWN |
| Observation: NOT_STARTED / WINDOW_OPEN / WINDOW_MATURE / WITHDRAWN / UNKNOWN | NOT_STARTED |
| Distinct later research case reference and why different | null |
| Self-initiated reuse evidence, actual operation and occurrence date | UNKNOWN |
| Later case's result, assistance and original-budget references | UNKNOWN |
| Reuse event assessment, reviewer/date and missing evidence | UNKNOWN |
| Full 30-day observation maturity assessment and separate evidence | UNKNOWN |

No activation date means no calculable window or reuse rate. A day-5 self-initiated different research can establish an early reuse event while the observation remains `WINDOW_OPEN`; it cannot establish a mature 30-day window. Same-case reruns, official demo repetition, owner-operated work and stated intentions are not reuse. Do not use a PR/SDK release date or this template's creation date as an activation date. A mature window without evidence of reuse is not a positive reuse finding; unknown follow-up is not a measured zero.

## 10. Reviewed reporting and corrections

- Reporting cohort, denominator, observation interval and source records: UNKNOWN.
- Which specific reviewed facts may be included in which metric: UNKNOWN.
- Unknown/missing values and non-eligible cases retained alongside any summary: UNKNOWN.
- PR94 external reproduction status, if separately reviewed; otherwise no change: UNKNOWN.
- Reviewer/date and approved public summary reference: UNKNOWN.

Keep software qualification, PR94 external reproduction and own-case activation/value/reuse separate. Do not count this template, illustrative examples, copied environments or multiple attempts as new people. Case notes do not automatically update any live gate.

### Correction entry — append only for an actual correction

- Correction reference and actual author/date/timezone: UNKNOWN.
- Earlier entry and preserved original reference: null.
- What was wrong or previously unknown, and the corrected statement: UNKNOWN.
- Reason, new evidence and review attribution: UNKNOWN.
- Effect on technical outcome, participation, activation, decision, reuse and any published summary, assessed separately: UNKNOWN.
- Permitted publication/notification action, if any: UNKNOWN.

Retain failure and uncertainty history. A later review may correct a classification; it cannot manufacture past participation, consent, an execution receipt, an unconsumed budget slot or an elapsed observation window.
