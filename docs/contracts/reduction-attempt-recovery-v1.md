# Reduction attempt recovery v1

S10-02a, accepted by owner merge of [PR102](https://github.com/Darrenus/tickwitness/pull/102), 2026-11-07 (Asia/Singapore). [Story #29](https://github.com/Darrenus/tickwitness/issues/29), [ADR 0033](../adr/0033-read-only-reduction-recovery.md), [Sprint 10](../planning/sprint-10-status.md). This remains a read-only recovery audit. The [managed native extension](native-reduction-jobs-v1.md) is reviewed separately; explicit retry and Job acknowledgment recovery remain later S10-02 work. External human reproduction remains **0 / PENDING**.

## User need and authority

A reduction producer may lose its response after the original attempt outcome was committed. Starting another native run immediately would spend another research slot and could hide the already committed result. An operator can now locate the original attempt, independently reverify its frozen preparation and source, and recover the existing final manifest without execution or repair.

The audit requires the original live ledger, attempt ID, preparation ID, source bundle ID and finding report ID. A portable source is evidence of an observed prefix; it cannot restore slots, establish a replacement budget or authorize another execution. All queries are restricted to development. Confirmation is denied before identifier, package or ledger access.

## Observed states

| Status | Required facts | Recovery disposition |
| --- | --- | --- |
| `reserved_without_intent` | Exact original reservation; no intent or outcome observed | `owner_review_required`; the requested preparation is not bound to this attempt |
| `reserved_unfinalized` | Exact reduction intent and all four preparation CAS objects; no outcome observed | `new_original_attempt_required_for_execution`; no authorization is granted |
| `committed_failure` | Exact original reservation and intent, valid committed reduction failure | `failure_reverified`; retain the consumed slot |
| `committed_result` | Existing final receipt and result closure independently reconstructed by `inspect_reduction_run` | `result_reverified_without_execution`; return the original final manifest |

A missing ledger or reservation is a missing-evidence error. A mismatched preparation, non-reduction intent, malformed outcome, conflicting pins or missing closure is an error, never an unfinished state. A baseline or scenario attempt is not a reduction recovery target.

An absence is an observation during a read, not a sealed assertion that a concurrent coordinator can never append an intent or outcome. The audit does not lock or authenticate the global history. In the unbound state the audit verifies the requested preparation itself, but explicitly does not claim that this preparation belongs to the attempt.

## Report

The canonical `reduction_attempt_recovery_v1` report has schema version 1 and is bounded at 128 KiB. Its exact fields are `kind`, `schema_version`, `source`, `preparation_id`, `attempt`, `status`, `recovery`, `bindings`, `final_manifest` and `verification`.

`source` pins the bundle, report and original protocol IDs. `attempt` is the existing original reservation, including the consumed slot and per-attempt wall budget. `bindings` contains the observed intent and outcome IDs; `run_id` exists only for a committed result and equals the outcome ID. `final_manifest` is that exact `reduction_run_receipt_v1` document, otherwise null. The receipt remains the final research manifest; this audit does not publish a competing manifest or upgrade a terminal projection into a checkpoint.

`recovery.restart_mode` is `frozen_origin_new_attempt_only_v1`. Both `checkpoint_supported` and `execution_authorized` are false. Current adapters expose terminal projections, not the complete queue, strategy and RNG state required for checkpoint resume. A future actual rerun must start from the frozen origin and consume a new slot under the same original protocol. An interrupted or failed attempt is never refunded or reused for free execution.

Verification distinguishes source/preparation/prefix/reservation checks, preparation binding/CAS checks and terminal revalidation. Binding and preparation CAS are false for an unbound attempt; terminal revalidation is true only for the two committed states. `observation_only` is true. Attempt reservation, native replay, research publication, Job mutation, checkpoint restoration, retry, refunds and global absence/authenticity claims are all false.

Report structure and hash consistency do not prove native execution or source authenticity by themselves. The application independently opens the source and original ledger and rebuilds the preparation, intent and terminal evidence. A result may have an `incomplete` native execution status and still be a valid committed receipt; recovery does not certify a completed strategy, preserved counterexample or profitable result.

## CLI and failure behavior

```sh
tickwitness inspect-reduction-attempt ATTEMPT_ID /owner/prepared-prefix \
  --expected-preparation-id PREPARATION_ID \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID \
  --input-root /owner/inputs --source-evidence portable/source \
  --runs /owner/original-runs
```

Valid reports, including failures and unfinished observations, exit 0. Consumers must read `status` and `recovery`; exit 0 is not research success or permission to run. Existing error semantics remain: invalid evidence 2, store/integrity/uncertain IO 3, missing evidence 4, confirmation 5. There is no checkpoint parameter, write/output target, automatic retry or Catalog access. Repeated inspection of unchanged evidence returns the same report bytes and leaves all source/ledger bytes unchanged.

Research publication and Job publication are different stores. Existing research publication writes CAS artifacts first, then one immutable outcome name. A producer exception cannot establish that publication did not occur. This audit can independently reverify a committed research outcome after lost acknowledgment, but cannot transition a Job or claim an atomic transaction across SQLite and the file ledger. Later managed execution must fence research publication before acknowledging Job success.

## Qualification boundary

Remote CPU tests cover all four states, invalid bindings and closure, missing evidence, confirmation before IO, publication uncertainty and immutable records. Installed core-only verification forbids native imports, subprocesses, network, reservation, intent binding and publication. Native profiles reuse the already frozen original five-slot reduction lifecycle; they do not append a sixth attempt, inflate its budget or reuse the historical eleven-slot Job qualification as writable credit.

Actual core, Ubuntu, macOS and source-archive/installed-wheel results are recorded in the implementation PR and `reduction-execution-*` artifacts. Unit fixtures are not native interruption evidence. The installed profiles record their actual observed states and acknowledgment-loss experiment; any unexercised crash/retry/fencing scenario remains unqualified. No release or external-human gate is completed by automation.
