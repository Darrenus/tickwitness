# Inspection evidence absence context v1

Status: FROZEN before implementation, 2026-11-28. S14-02a / F02 / #41.
This contract and [ADR0053](../adr/0053-inspection-absence-context.md) must be
committed, actually pushed and their exact remote revision read back before
implementation. Forecast8h = contract2 + implementation3 + remote acceptance2
+ documentation1, drawn once from S14-02's original12h pool. With accepted
S14-01a8h, the original32h has16h uncommitted: parent01's4 + parent02's4
+ parent03's8. These are forecasts, not actual hours or new research budget.

## Observed problem and boundaries

The existing CLI routes executable-registry/attempt NotFound to
research_evidence_not_found/exit4 and DatasetNotFound to dataset_not_found/exit4.
Their JSON has code/message but no machine-readable association between the
requested experiment/attempt and a failed dependency lookup. Existing real
filesystem negatives cover missing roots, unpublished IDs and reservation CAS
orphans. This is maintainer-observed diagnostic friction, not an invented
external-user request. MCP/HTTP remain DEFER; verified participant demand UNKNOWN.

Only improve inspect-experiment and inspect-attempt. Keep their application
services, storage adapters, domain aggregates, persisted schemas, receipts,
SQLite ownership/recovery, v1 SDK five methods/seven exports and all other CLI
error routes unchanged. Do not interpret an error message to guess identity.

## Typed adapter context

A private-to-the-CLI integration error, InspectionNotFoundError(ValueError),
wraps only the existing known ExecutableProtocolNotFoundError,
DatasetNotFoundError or AttemptNotFoundError at the actual lookup boundary.
Preserve the original human message and exception cause. Carry code, fixed
reason=inspection_evidence_not_found, command, requested_id, lookup and optional
resource_id. Add no new domain result, application port or execution capability.

| command | lookup | existing code / exit | resource_id |
| --- | --- | --- | --- |
| inspect-experiment | executable_registry | research_evidence_not_found /4 | omitted |
| inspect-experiment | dataset_store | dataset_not_found /4 | omitted |
| inspect-experiment | executable_protocol | research_evidence_not_found /4 | actual protocol ID passed to get |
| inspect-experiment | referenced_dataset | dataset_not_found /4 | actual dataset ID passed to get |
| inspect-attempt | attempt_ledger | research_evidence_not_found /4 | omitted |
| inspect-attempt | committed_attempt | research_evidence_not_found /4 | requested attempt ID |

requested_id always remains the command's validated input identity, even when
resource_id identifies a different referenced dataset. Constructor failures do
not invent a resource identity. A dataset reference comes only from the existing
application's validated protocol read and actual DatasetReader.get call, never
from an unverified file, message substring or speculative second lookup.

Preserve inspect-experiment's exact eager order: construct registry(create=False),
construct DatasetStore(create=False), then call the existing application service.
Private read-only delegating registry/dataset adapters may add context to get;
they must not duplicate protocol parsing/verification or reorder dependency reads.
inspect-attempt constructs ledger(create=False), then calls its existing service;
wrap that whole committed-attempt lookup without guessing CAS versus slot.

CLI stderr retains existing code/message and exit4, adding only the fixed fields
above. Omit resource_id when unknown rather than using null or the requested
protocol ID as a substitute for a missing store. Successful stdout remains
byte-for-byte the existing projection; failed commands emit no success stdout.
No budget_consumed, budget_available, refund, execution/retry permission, source
authentication, repair recommendation, filesystem root or host field is added.
The unchanged human message is not a parsing contract or a path-secrecy promise.

Example for a missing referenced dataset:

~~~json
{"error":{"code":"dataset_not_found","message":"existing human diagnostic","reason":"inspection_evidence_not_found","command":"inspect-experiment","requested_id":"64-character protocol ID","lookup":"referenced_dataset","resource_id":"actual 64-character dataset ID"}}
~~~

## Preserve refusal and accounting semantics

This reports an existing typed NotFound route at an observed lookup; it does not
establish OS-level ENOENT, a transactionally complete snapshot, global absence,
never-executed history or budget availability. Existing root prechecks use
Path.exists; this slice does not strengthen or rewrite their classification.
Ordinary OSError, permission, malformed/hash-mismatched evidence, unsafe paths,
reference mismatch and other non-NotFound errors retain their existing routes
and receive no inspection context. Missing registry/ledger structural directories
that currently fail generically stay generic; a missing protocol slot namespace
inside get_reservation currently belongs to the committed-attempt NotFound route
and is not reclassified.

A reservation needs its CAS and exact protocol-slot closure. A CAS orphan is not
a committed attempt; report the current NotFound route without guessing which
component disappeared, whether execution occurred, or whether another slot is
available. Do not search another store or scan unrelated attempts.

A valid committed reservation with no outcome still succeeds as
state=reserved_unfinalized, budget_consumed=true, outcome=null. A finalized
failure is still a consumed finalized attempt. A committed outcome with a missing
CAS closure remains integrity refusal/exit3, not NotFound or unfinalized success.
No reservation, final receipt or existing protocol is created, repaired, refunded,
replayed, acknowledged, retried or rewritten by either inspection command.

## Installed verification and remote acceptance

All project execution is remote. Unit/integration negatives use disposable
synthetic state; installed checks reuse copies of the existing smoke workflow's
already frozen protocol, datasets and consumed attempt before those source trees
are deleted. No additional freeze, reserve, replay or original-user-ledger action
is permitted for the new diagnostic cases. Preserve all existing budgeted smoke
steps and their budgets.

The installed driver runs a fixed bounded matrix of at most16 inspection calls,
with a shared90s limit and each child at most15s. Before CLI import it rejects
native-engine imports, worker/network construction and known research publication/
reservation methods. DatasetStore's existing SQLite mode=ro connections remain
allowed and are checked; this is not baseline bundle verification's no-SQLite
profile and not a hostile-code sandbox.

Snapshot source trees and compare persistent application evidence names/bytes
around each inspection. Only the target store's known catalog.sqlite3-wal/catalog.sqlite3-shm runtime
sidecars and directory metadata may change during legitimate read-only access; keep this explicit rather
than claiming a filesystem with no writes at all. Catalog/CAS/protocol/slot/outcome
bytes remain unchanged. Do not delete or repair live sidecars to pass a check.

The full real positive/negative/unknown matrix below is covered by unit and
integration tests; installed acceptance uses at most16 representative calls.
Required cases include:

1. Valid experiment and finalized/unfinalized attempt receipts remain unchanged;
   unfinalized inspection stays budget_consumed=true without engine or reservation.
2. Each of the six lookup boundaries supplies exact code, fixed fields and only
   actually known resource IDs. Separately omit each referenced dataset and verify
   the actual requested dependency ID, not the outer protocol ID.
3. Dual faults preserve eager construction and existing read priority. Invalid
   command IDs fail argument parsing before I/O. Other commands/SDK retain their
   previous errors and public surface.
4. CAS orphan, missing slot namespace, absent outcome pointer and missing outcome
   CAS closure are distinguished according to existing accounting semantics.
5. Permission/OSError, malformed/corrupt evidence, symlink/FIFO, currently non-NotFound structural-directory failures (excluding
   the protocol-slot namespace case above) and identity/reference mismatch retain
   original non-NotFound
   refusal without fabricated context. No automatic recovery or successful result.
6. Capture the new source/actual CI checkout/tree, focused JUnit, successful
   enclosing job exits, installed outputs and complete terminal metadata/logs.
   Previous green checks, a pytest summary alone, skips or startup refusal do not
   count as current-head acceptance. No desktop project imports/tests/lint/builds.

M1 remains DISABLED/not integrated; M2 unsupported; independent human security
NOT_PERFORMED/reviewerUNASSIGNED and external-human0/0/PENDING. Original5/8/11,
golden, PR94, actual reference24+prior21=45 and600/10/2 windows are unchanged.
No AWS Start, new qualification, original-host export/oldACK, outreach, listener
or release is granted. All CLOSED evidence scopes remain immutable.
