# Job result refusal context v1

Status: FROZEN before implementation, 2026-11-28. S14-02b / F03 / #41.
This contract and [ADR0055](../adr/0055-job-result-refusal-context.md) must be
docs-only committed, actually pushed and their exact remote revision read back
before code changes. Forecast4h = contract1 + implementation1 + remote acceptance1
and documentation1, selected once from parent02's remaining4h. Original S14
32h = accepted16 + selected4 + uncommitted12 (parent01's4 + parent03's8).
These are forecasts, not actual effort or additional research budget.

## Observed consumer problem

`read-job-result` already refuses a validated non-SUCCEEDED Job with
`job_conflict` / exit9 and message `Only a succeeded Job has a readable result`.
The existing CLI test and installed `smoke_jobs.py` QUEUED/FAILED consumers only
check that generic code. The same code also covers unrelated ownership/version,
terminal, SQLite BUSY and optional-journal conflicts. The existing finite read-
conflict reread permission cannot be inferred from every exit9.

This is a maintainer-observed automation diagnostic gap, not verified external
user demand. Only enrich the existing CLI state-refusal branch. MCP/HTTP remain
DEFER/demand UNKNOWN. No new application port, domain rule, SDK method/export,
Catalog schema, snapshot, event, result, worker or persistent research format.

## Exact typed CLI boundary

Add a CLI-local `JobResultNotSucceededError(JobConflictError)`. Raise it only
where the existing `read-job-result` branch has first validated the requested
identity, constructed `SqliteJobStore(create=False)` and successfully completed
the full existing `store.get(requested_id)` validation. The known snapshot's
persisted state is one of QUEUED, RUNNING, FAILED or LOST. Preserve the original
human message, code and exit9; add exactly four fields:

```json
{"error":{"code":"job_conflict","message":"Only a succeeded Job has a readable result","reason":"job_result_not_succeeded","command":"read-job-result","requested_job_id":"64 lowercase hexadecimal characters","stored_state":"QUEUED"}}
```

`requested_job_id` is the command's validated identity. `stored_state` comes
solely from that fully verified snapshot. It is a past read observation, not a
current terminal guarantee or effective state. Do not read clocks/locks again,
call `job_view`, compute COORDINATOR_LOST/LEASE_EXPIRED/CLOCK_UNCERTAIN, invent a
persisted CANCELLED state, parse error messages or perform a speculative lookup.
The four-state refusal never calls `store.result` or starts execution.

CLI handles this specific subtype before the existing generic JobStoreError
handler. Failed reads have empty success stdout. No path, host, token, nonce,
budget counter, retryable flag, execution/repair recommendation or permission
field is added. Other commands and direct application/Store callers keep their
existing errors. This is not a general conflict taxonomy or a new result receipt.

## Preserve success, corruption and uncertainty

For SUCCEEDED, retain both original calls: verified `get`, then `result`.
Successful output remains exactly the saved canonical operation-result bytes,
without a new newline or wrapper. A Job can succeed while its domain result is
NOT_EVALUABLE; preserve that result and null domain truth/value.

`get` validates snapshot/index/hash/latest event and result BLOB. A SUCCEEDED
row with missing/corrupt BLOB, an unsuccessful row with an unexpected BLOB, or a
malformed snapshot/event remains integrity3 before new context can be created.
Missing Job/Catalog stays4. Permission, unsafe path, ordinary IO, SQLite BUSY,
optional-journal or ownership/version errors keep their existing generic route
without fabricated state, even if their message resembles the refusal text.

`get` and `result` are separate read transactions, not an atomic combined
snapshot. Exceptions from the second `result` call retain their old route.
The existing defensive `raw is None` / `Job result is unavailable` fallback
remains generic conflict9 with no new context. Do not infer the second read's
facts from the first snapshot or broaden any catch/retry loop.

Absence of the new reason does not certify a retryable conflict. FAILED/LOST
does not authorize a research retry, refund or checkpoint restoration. A later
real execution still needs the same original protocol's new available slot;
an already committed result must not execute again.

## Remote acceptance and read-only checks

All project execution remains remote. Use disposable real Catalog fixtures and
the existing pinned result artifacts; prepare stored states through existing
domain transitions without worker/native/research execution. After preparation,
guard mutation/coordinator/reconciliation, worker/native, network and research
publication/reservation paths. Permit only the existing read-only Job Catalog
SQLite connections. Compare every Catalog name/type/regular-file byte around
queries; directory clocks/atime are not an immutability promise. Exclude no WAL,
SHM or journal: this Store already rejects WAL/SHM, unlike the DatasetStore
profile used by F02. These checks are not a hostile-code sandbox.

1. Positive: real SUCCEEDED result bytes unchanged, including domain-unknown
   results; old CLI/SDK/application outcomes remain unchanged.
2. Counterexample: each four-state refusal has exact fields/code/message/exit9,
   empty stdout, no second result read and unchanged Catalog/ledger. A RUNNING
   snapshot remains stored RUNNING even after coordinator ownership ends.
3. Unknown/refusal: malformed IDs before IO, missing Catalog/Job, corrupt BLOB/
   snapshot/event/index, unsafe paths, permissions, real bounded BUSY and injected
   original conflicts remain generic. Separately cover the second result call's
   exceptions and None fallback, with no new state fields or automatic retry.
4. Strengthen the installed smoke's existing QUEUED and core FAILED result reads
   to check exact context and unchanged Catalog inventory. Reuse its existing
   SUCCEEDED byte checks, transcripts, guards and original research fixtures.
   Add no freeze/reserve/replay or Job execution for the new diagnostic cases;
   keep all existing smoke calls, deadlines, budgets and failure controls.
5. Save current source/actual CI checkout/tree, focused JUnit, successful
   enclosing jobs and installed output. Require the current source's complete
   17-job Engineering matrix; previous green or pytest alone is not acceptance.
   Preserve real failures, skips and startup refusals as their actual outcomes.

M1 DISABLED/not integrated, M2 unsupported, independent security NOT_PERFORMED/
reviewerUNASSIGNED and external-human0/0/PENDING remain. Original5/8/11, golden,
PR94, actual24+prior21=45 and600/10/2 windows are unchanged. No AWS Start/new
qualification/original24 rerun, original-host export/oldACK, reset/refund,
committed-result rerun, outreach, listener or release. CLOSED evidence is immutable.
