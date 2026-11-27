# ADR0051: Automate bounded evidence receive and recover existing final records

Status: ACCEPTED and frozen before implementation (2026-11-27).

## Context

The actual fourth EC2 qualification on source908d56d committed24 PASS controls,
24 current/45 cumulative accounting and a matching report/state/original-boot
receipt. Its initial archive was completely downloaded. Operator verification
finished after the original120s handoff; the sole ACK connection timed out and
later ACK/controller-result/export stream records were not retrieved. The VM
automatically stopped. Qualification success did not close evidence transport.

Replaying the qualifier/exporter, extending the old wait, generating another
receipt or backdating an ACK would alter the evidence rather than recover it.
The old source and604-file audit must remain immutable.

## Decision

Freeze the separate [transport/readback contract](../contracts/restricted-reference-ec2-transport-v1.md)
before implementation. Add standalone stdlib reader and receiver operations,
outside the existing qualification closure and without changing the908 server
helper or original lifecycle protections.

Prepare and authenticate receive channels before ready. A conservative deadline
derived from an authenticated server monotonic observation only shrinks; all
download, semantic verification and fsync costs consume it. Fsync a permanent
local one-use ACK-intent before the sole exact ACK. Open the independent bounded
post-record channel before ACK to reduce the service-shutdown capture race.
Missing replies never authorize a retransmission or an inferred successful exit.

For the existing run, use only fixed observational readback
`ec2-readback-20261127-run0004-01`, not live ACK. Preserve shared last-result bytes
before one unchanged sleep300 lifecycle guard. Read original post-records and
exact old journals, compare original pins before/after and independently observe
Stop. Genuine absence, malformed bytes and original handoff failure remain facts.
A new verified readback receipt can close collection without changing history.

Keep receiver execution remote and independent. Existing desktop SSH and inert
byte inspection may collect historical records; they do not authorize local
project execution, uploading the owner's key to CI, granting another runtime
access, or treating a same-host read as independent archive download.

## Consequences

The24/45 qualification result and research common budget remain unchanged.
There is no new qualification permission or automatic fifth run. Precompiled
verification, one deadline and preauthenticated post-record capture address the
observed client delay and shutdown race. Remote tests must use actual production
operations and durable fixtures, with honest synthetic scope labels.

Original /var/lib evidence and ready/archive have persisted stat pins. The ten
source closure files retain original bytes/hash evidence but not a complete
persisted original inode set; the audit must preserve this distinction.

The separate recovery audit records both the original handoff outcome and the
new retrieval outcome. M1 remains disabled; human security and external-human
reproduction gates remain pending regardless of automated test success.
