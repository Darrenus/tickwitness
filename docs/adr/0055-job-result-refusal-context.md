# ADR0055: Attribute a validated non-succeeded Job result refusal

Date: 2026-11-28. Status: accepted design for S14-02b/F03; implementation and its
own remote qualification/owner acceptance remain pending.

## Context

The existing `read-job-result` consumers in the CLI regression and installed
Job smoke receive only `job_conflict`/9 for a known QUEUED or FAILED snapshot.
The same code also represents unrelated transient reads and ownership/version
refusals. Existing permission to retry a bounded read conflict does not apply to
all exit9 results. A consumer needs to identify this one known refusal without
guessing from diagnostic prose or changing Job/research semantics.

## Decision

Freeze and actually push/read back the [v1 CLI contract](../contracts/job-result-refusal-context-v1.md)
before code. Add a CLI-local JobConflictError subtype only at the existing branch
after complete `store.get` validation. Preserve code9/message, add fixed reason,
command, validated requested_job_id and observed stored_state. Cover exactly
QUEUED/RUNNING/FAILED/LOST; successful result bytes and all generic routes stay.

Do not catch/relabel get failures, compute effective state or treat get/result
as one transaction. A second result exception or defensive None remains its old
generic refusal. Real missing/corrupt successful BLOB and unexpected unsuccessful
BLOB remain integrity3 from Store validation. No application/infra/SDK/schema
changes, new Job attempt or retry authority.

Use real Catalog transitions and pinned artifacts in remote tests, with guards
after setup. Strengthen existing installed reads and saved transcripts rather
than executing new research. Keep the original complete17-job CI gate and
runtime/qualification/human boundaries. Forecast4h from parent02 completes its
original12h selection; S14 remains16accepted+4selected+12uncommitted of32h.

## Alternatives and consequences

Parsing messages is not a stable machine contract. A global Job conflict taxonomy
or SDK Job surface would enlarge frozen APIs without consumer evidence. Tagged-
pair missing-CAS diagnostics is a real separate candidate with twelve-role IO/
race acceptance, retained unselected rather than running parallel work.

This additive error describes only a validated historical snapshot. It does not
establish current state, result availability, retryability, budget or research
truth. The absence of its reason certifies nothing about another conflict. M1
and human-review gates stay closed/pending; original protocol budgets remain.
