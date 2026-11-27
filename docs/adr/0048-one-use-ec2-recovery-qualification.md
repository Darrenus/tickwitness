# ADR0048: One explicit EC2 recovery qualification with retained history

Date: 2026-11-26 Asia/Singapore. Status: accepted for the bounded internal
reference after independent review and actual freeze push/readback; this is not
product M1 acceptance or permission to bypass the operator's instance Start.

## Problem

The first EC2 attempt was NOT_QUALIFIED before its positive guest gate because
the trusted controller's private umask masked input directory search permission.
The correction has passed remote source checks, but the permanent host claim and
poisoned terminal run correctly refuse another invocation. Deleting the claim,
changing a nonce, reopening an old monotonic window or using only the remaining23
controls would discard charged history or fail to qualify one complete new tuple.

## Decision

Freeze [one-use recovery v1](../contracts/restricted-reference-ec2-recovery-v1.md)
before implementation. Permit exactly one additional technical24-case/600s
invocation and original30s setup, retaining the predecessor's1charge and all
immutable records, with cumulative actual cap25. No research protocol/Job/family
budget changes. All24 cases must independently pass on one corrected new source.

Use the original host claim as a read-only held global flock. A fixed root plan
binds exact predecessor hashes, current implementation/source lock, one plan/run
ID and the trusted owner's previous AWS Stop observation. Exclusively consume
one global recovery record durably before new-run creation, IMDS or policy.
Partial/uncertain consumption remains used; no automatic third invocation exists.

Use separate strict recovery record kinds and ten-file source closure, preserving
default v1 shapes and old GHA opaque refusal. Preserve original runtime controls,
explicit manually attached policy and independent task observations. Final
report/terminal/receipt bind predecessor lineage and actual cumulative accounting;
unknown counts remain unknown or lower-bound, never authoritative stale zero.

## Consequences and limits

This adds a narrowly pinned successor path, not general recovery, a mutable host
ledger, arbitrary-source execution or research access. Root owner/provisioning,
full repository, OS and transitive runtime remain trusted. Historical AWS Stop
is owner evidence, not signed cloud attestation. Exact source tests cannot replace
the next actual host qualification; the instance remains stopped during source
work. No policy unload, global control relaxation or automatic Start is allowed.

Every attempt retains bounded evidence and ends under the existing automatic
Stop supervisor with independent AWS readback. M1 product remains DISABLED,
PR115 Draft/#38 incomplete, independent human security review NOT_PERFORMED,
and external-human research reproduction0/0/PENDING until their own gates pass.
