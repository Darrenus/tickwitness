# ADR0052: Diagnose missing baseline CAS objects without adding authority

Status: ACCEPTED / FROZEN before implementation (2026-11-27).

## Context

Owner accepted PR116's bounded S13-03 preparation and authorized the next step
with M1 disabled and external reproduction pending. S14 transport work remains
conditional: no verified CLI/SDK task blockage or participant demand has been
provided. Its existing fallback permits evidence-backed core diagnostics within
the same32h rather than adding MCP/HTTP work beside it.

The baseline reader's actual negative tests delete a manifest or declared CAS
leaf but both receive a generic missing-entry error. The CLI preserves that
failure as integrity/IO exit3 without identifying the declared object. The
search profile demonstrates an existing role/SHA diagnostic pattern. This is
observable maintainer friction, not evidence of external demand.

## Decision

Freeze the [additive diagnostic contract](../contracts/baseline-evidence-diagnostics-v1.md),
commit/push it and read the remote revision before implementation. First slice
S14-01a/#40 forecasts8h (contract2, implementation3, remote acceptance2, docs1)
inside the original32h; the remaining24h is uncommitted. The original S14 parent
story ceilings12/12/8 remain forecasts, not additional selected transport work.

Add one infrastructure `BundleError` subtype for an observed missing
manifest-declared object leaf, deterministic role aliases/SHA, and an additive
CLI `reason`/context projection. Preserve baseline error code and exit3, missing
root exit4, valid receipts, strict tree/format limits and all nonabsence errors.
Do not change generic tree checking for unrelated callers or borrow the search
profile's distinct error code. Infrastructure facts do not decide research
validity; semantic/accounting verification remains in the application layer.

## Consequences

Users can identify declared missing bytes while existing code/exit consumers
remain compatible. A first missing object is not an exhaustive health report,
source authentication or successful semantic closure. Missing manifests and
containers cannot invent an object identity, and permission/unsafe/corrupt
inputs retain generic refusal.

No new persisted schema, domain aggregate, SDK method, runtime mode, repair,
network, worker, ledger, replay or reservation authority follows. Tests use
disposable synthetic copies and real installed CLI output remotely; old
qualification/committed artifacts and common budgets remain intact. M1 stays
off; reviewer/adoption gaps and HTTP/MCP DEFER remain explicit. Any unrelated
future diagnostics must be separately refined from evidence, not invented to
fill the remaining capacity.
